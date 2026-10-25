import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
import socket
import threading
import json
import os
from datetime import datetime
import xml.etree.ElementTree as ET
import webbrowser
import time

class BoseQuadManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Bose SoundTouch Quad-Manager")
        self.root.geometry("800x900")
        self.config_path = os.path.expanduser("~/.bose_manager_config.json")
        self.discovered_speakers = {} 
        self.selected_speaker_ip = tk.StringVar()
        self.is_open_network = tk.BooleanVar(value=False)
        self.dark_mode = tk.BooleanVar(value=True)
        self.load_settings()
        self.setup_ui()
        # Apply default theme on startup
        self.toggle_theme()

    def load_settings(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    self.discovered_speakers = data.get("speakers", {})
                    last_ip = data.get("last_selected_ip", "")
                    self.selected_speaker_ip.set(last_ip)
            except Exception as e: print(f"Error loading config: {e}")

    def save_settings(self):
        data = {"speakers": self.discovered_speakers, "last_selected_ip": self.selected_speaker_ip.get()}
        try:
            with open(self.config_path, 'w') as f: json.dump(data, f)
        except Exception as e: print(f"Error saving config: {e}")

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = f"[{level}]"
        formatted_msg = f"{timestamp} {tag: <10} {message}\n"
        self.root.after(0, self._write_to_log, formatted_msg)

    def _write_to_log(self, msg):
        self.log_panel.insert(tk.END, msg)
        self.log_panel.see(tk.END)

    def setup_ui(self):
        # Theme setup
        self.style = ttk.Style()
        
        # Header Frame for the toggle
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Dark Mode Toggle (Placed in a header frame to ensure visibility)
        self.theme_toggle = ttk.Checkbutton(header_frame, text="🌙 Dark Mode", variable=self.dark_mode, command=self.toggle_theme)
        self.theme_toggle.pack(side=tk.RIGHT)

        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)
        self.tabControl = ttk.Notebook(main_container)
        self.tab_setup = ttk.Frame(self.tabControl)
        self.tab_control = ttk.Frame(self.tabControl)
        self.tab_pairing = ttk.Frame(self.tabControl)
        self.tab_danger = ttk.Frame(self.tabControl)
        self.tabControl.add(self.tab_setup, text=' 🛠️ Initial Setup ')
        self.tabControl.add(self.tab_control, text=' 🔊 Control Center ')
        self.tabControl.add(self.tab_pairing, text=' 👯 Zone Management ')
        self.tabControl.add(self.tab_danger, text=' ⚠️ Danger Zone ')
        self.tabControl.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.build_setup_tab()
        self.build_control_tab()
        self.build_pairing_tab()
        self.build_danger_tab()
        log_frame = ttk.LabelFrame(main_container, text=" Event Log ", padding="10")
        log_frame.pack(fill=tk.X, padx=10, pady=10)
        self.log_panel = scrolledtext.ScrolledText(log_frame, height=12, font=("Consolas", 9))
        self.log_panel.pack(fill=tk.X)
        self.log("Application started.")
        self.update_speaker_lists()

    def toggle_theme(self):
        if self.dark_mode.get():
            # Dark theme colors - Unified Deep Dark
            bg_color = "#1e1e1e"
            fg_color = "#dcdcdc"
            accent_color = "#2a2a2a"
            
            self.root.config(bg=bg_color)
            self.style.configure("TFrame", background=bg_color)
            self.style.configure("TLabel", background=bg_color, foreground=fg_color)
            self.style.configure("TCheckbutton", background=bg_color, foreground=fg_color)
            self.style.configure("TButton", background=accent_color, foreground=fg_color, borderwidth=0)
            self.style.configure("TLabelFrame", background=bg_color, foreground=fg_color, bordercolor=bg_color)
            self.style.configure("TLabelFrame.Label", background=bg_color, foreground=fg_color)
            
            # Notebook needs special handling
            self.style.configure("TNotebook", background=bg_color, borderwidth=0)
            self.style.configure("TNotebook.Tab", background=accent_color, foreground=fg_color, borderwidth=0)
            
            # Match the log panel exactly
            self.log_panel.config(bg="#1e1e1e", fg="#dcdcdc", insertbackground="white")
        else:
            # Light theme colors
            bg_color = "#f0f0f0"
            fg_color = "#000000"
            
            self.root.config(bg=bg_color)
            self.style.configure("TFrame", background=bg_color)
            self.style.configure("TLabel", background=bg_color, foreground=fg_color)
            self.style.configure("TCheckbutton", background=bg_color, foreground=fg_color)
            self.style.configure("TButton", background="#e1e1e1", foreground=fg_color)
            self.style.configure("TLabelFrame", background=bg_color, foreground=fg_color)
            self.style.configure("TLabelFrame.Label", background=bg_color, foreground=fg_color)
            
            self.style.configure("TNotebook", background=bg_color)
            self.style.configure("TNotebook.Tab", background="#e1e1e1", foreground=fg_color)
            
            self.log_panel.config(bg="white", fg="black", insertbackground="black")

    def add_reset_links(self, parent_frame, target_tab=None):
        link_frame = ttk.Frame(parent_frame)
        link_frame.pack(pady=10)
        st10_link = ttk.Label(link_frame, text="SoundTouch 10 Reset", foreground="blue", cursor="hand2")
        st10_link.pack(pady=2)
        st10_link.bind("<Button-1>", lambda e: webbrowser.open("https://support.bose.com/article/soundtouch-10-resetting-your-product"))
        wifi_link = ttk.Label(link_frame, text="Access Local Wi-Fi (Setup Mode)", foreground="blue", cursor="hand2")
        wifi_link.pack(pady=2)
        wifi_link.bind("<Button-1>", lambda e: webbrowser.open("https://support.bose.com/article/soundtouch-10-connecting-to-a-wi-fi-network"))
        other_link = ttk.Label(link_frame, text="Other Models", foreground="blue", cursor="hand2")
        other_link.pack(pady=2)
        other_link.bind("<Button-1>", lambda e: webbrowser.open("https://support.bose.com/"))
        if target_tab:
            nav_text = "Go to Initial Setup" if target_tab == self.tab_setup else "Go to Setup Tab"
            setup_link = ttk.Label(link_frame, text=nav_text, foreground="blue", cursor="hand2")
            setup_link.pack(pady=10)
            setup_link.bind("<Button-1>", lambda e: self.tabControl.select(target_tab))
        return link_frame

    def build_setup_tab(self):
        frame = ttk.Frame(self.tab_setup, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        instr = ("For each new speaker:\n1. Hold '2' and 'Volume -' until LED is amber.\n"
                 "2. Connect Ubuntu Wi-Fi to 'Bose SoundTouch XXXX'.\n"
                 "3. Enter your home Wi-Fi details and click 'Join Wi-Fi'.")
        ttk.Label(frame, text=instr, wraplength=500, justify=tk.LEFT, foreground="blue").pack(pady=10)
        self.add_reset_links(frame)
        input_f = ttk.Frame(frame, padding="10")
        input_f.pack(pady=20)
        ttk.Label(input_f, text="Home SSID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.setup_ssid = ttk.Entry(input_f, width=30)
        self.setup_ssid.grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(input_f, text="Home Password:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.setup_pass = ttk.Entry(input_f, show="*", width=30)
        self.setup_pass.grid(row=1, column=1, padx=5, pady=5)
        self.open_net_check = ttk.Checkbutton(input_f, text="Network is Open (No Password)", 
                                             variable=self.is_open_network, command=self.toggle_pass_field)
        self.open_net_check.grid(row=2, column=0, columnspan=2, pady=10, sticky=tk.W)
        ttk.Button(frame, text="Join Wi-Fi", command=self.provision_wifi).pack(pady=10)

    def toggle_pass_field(self):
        self.setup_pass.config(state="disabled" if self.is_open_network.get() else "normal")

    def provision_wifi(self):
        ssid = self.setup_ssid.get().strip()
        if not ssid: return
        sec_type = "none" if self.is_open_network.get() else "wpa_or_wpa2"
        pw = "" if self.is_open_network.get() else self.setup_pass.get().strip()
        try:
            requests.post("http://192.0.2.1:8090/performWirelessSiteSurvey", data='<PerformWirelessSiteSurvey timeout="5"/>', timeout=5)
            payload = f'<AddWirelessProfile><profile ssid="{ssid}" password="{pw}" securityType="{sec_type}" /></AddWirelessProfile>'
            res = requests.post("http://192.0.2.1:8090/addWirelessProfile", data=payload, timeout=10)
            if res.status_code == 200: messagebox.showinfo("Success", "Credentials sent!")
        except Exception as e: messagebox.showerror("Error", f"Provisioning failed: {e}")

    def build_control_tab(self):
        frame = ttk.Frame(self.tab_control, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        select_f = ttk.LabelFrame(frame, text="Device Selection", padding="10")
        select_f.pack(fill=tk.X, pady=10)
        top_row = ttk.Frame(select_f)
        top_row.pack(fill=tk.X)
        ttk.Label(top_row, text="Active Speaker:").pack(side=tk.LEFT)
        self.speaker_combo = ttk.Combobox(top_row, textvariable=self.selected_speaker_ip, state="readonly")
        self.speaker_combo.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
        ttk.Button(top_row, text="🔍 Scan", command=self.start_discovery).pack(side=tk.LEFT)
        bottom_row = ttk.Frame(select_f)
        bottom_row.pack(fill=tk.X, pady=10)
        ttk.Label(bottom_row, text="Add Manual IP:").pack(side=tk.LEFT)
        self.manual_ip = ttk.Entry(bottom_row, width=20)
        self.manual_ip.pack(side=tk.LEFT, padx=10)
        ttk.Button(bottom_row, text="Add", command=self.add_manual_ip).pack(side=tk.LEFT)

    def add_manual_ip(self):
        ip = self.manual_ip.get().strip()
        if ip:
            self.discovered_speakers[ip] = "Manually Added"
            self.update_speaker_lists()
            self.save_settings()
            self.log(f"Manually added speaker {ip}", "SUCCESS")

    def on_volume_slide(self, value):
        vol_val = int(value)
        ip = self.selected_speaker_ip.get()
        if ip:
            threading.Thread(target=self.set_volume, args=(ip, vol_val), daemon=True).start()

    def mute_speaker(self):
        ip = self.selected_speaker_ip.get()
        if ip:
            threading.Thread(target=self.set_volume, args=(ip, 0), daemon=True).start()

    def set_volume(self, ip, value):
        # To control volume across a synchronized zone, we must send the command to the Master.
        # Most SoundTouch models accept /setVolume but for synchronized zones, 
        # the master usually propagates this to slaves if the payload is correct.
        
        # Try standard XML setVolume
        payload = f'<?xml version="1.0" encoding="UTF-8"?><setVolume value="{value}" />'
        try:
            res = requests.post(f"http://{ip}:8090/setVolume", data=payload, timeout=2)
            if res.status_code == 200:
                self.log(f"Volume set to {value} on {ip}", "SUCCESS")
                return
        except Exception as e:
            self.log(f"Volume set failed: {e}", "ERROR")

        # Fallback: Try GET request
        try:
            res = requests.get(f"http://{ip}:8090/setVolume?value={value}", timeout=2)
            if res.status_code == 200:
                self.log(f"Volume set to {value} (GET) on {ip}", "SUCCESS")
                return
        except Exception:
            pass

    def start_discovery(self):
        self.log("Starting SSDP scan...")
        threading.Thread(target=self.discover_speakers, daemon=True).start()

    def discover_speakers(self):
        msg = 'M-SEARCH * HTTP/1.1\\r\\nHOST: 239.255.255.250:1900\\r\\nMAN: \"ssdp:discover\"\\r\\nMX: 1\\r\\nST: urn:schemas-upnp-org:device:MediaRenderer:1\\r\\n\\r\\n'
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(3)
        try:
            sock.sendto(msg.encode(), ('239.255.255.250', 1900))
            while True:
                data, addr = sock.recvfrom(1024)
                if addr[0] not in self.discovered_speakers:
                    self.log(f"Found speaker at {addr[0]}", "SUCCESS")
                self.discovered_speakers[addr[0]] = "Bose Speaker"
        except socket.timeout:
            self.log("Scan complete.")
        finally:
            self.root.after(0, self.update_speaker_lists)

    def update_speaker_lists(self):
        ips = list(self.discovered_speakers.keys())
        self.speaker_combo['values'] = ips
        if self.selected_speaker_ip.get() in ips: self.speaker_combo.set(self.selected_speaker_ip.get())
        elif ips: self.speaker_combo.current(0)
        if hasattr(self, 'master_combo'): self.master_combo['values'] = ips
        if hasattr(self, 'slave_listbox'):
            self.slave_listbox.delete(0, tk.END)
            for ip in ips: self.slave_listbox.insert(tk.END, ip)

    def factory_reset(self):
        ip = self.selected_speaker_ip.get()
        if not ip:
            messagebox.showwarning("Error", "Please select a speaker first.")
            return
        if messagebox.askyesno("Confirm", f"Wipe all settings on {ip}?"):
            try:
                requests.get(f"http://{ip}:8090/resetDefaults", timeout=5)
                self.log(f"Factory reset triggered for {ip}", "SUCCESS")
                messagebox.showinfo("Success", "Reset command sent.")
            except Exception as e:
                self.log(f"Reset failed: {e}", "ERROR")
                messagebox.showerror("Error", f"Reset failed: {e}")

    def build_pairing_tab(self):
        frame = ttk.Frame(self.tab_pairing, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Create Synchronized Zone", font=("Arial", 12, "bold")).pack(pady=10)
        zone_f = ttk.Frame(frame)
        zone_f.pack(pady=10)
        ttk.Label(zone_f, text="1. Select Master Speaker:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.master_combo = ttk.Combobox(zone_f, state="readonly")
        self.master_combo.grid(row=0, column=1, padx=10, pady=5)
        ttk.Label(zone_f, text="2. Select Slave Speakers:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.slave_listbox = tk.Listbox(zone_f, selectmode=tk.MULTIPLE, height=6)
        self.slave_listbox.grid(row=1, column=1, padx=10, pady=5)
        btn_f = ttk.Frame(frame)
        btn_f.pack(pady=20)
        ttk.Button(btn_f, text="🚀 Sync All Selected", command=self.start_sync_thread).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_f, text="🔍 Verify Zone", command=self.verify_zone).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_f, text="❌ Clear Zone", command=self.clear_zone).pack(side=tk.LEFT, padx=10)

    def start_sync_thread(self):
        threading.Thread(target=self.sync_zone, daemon=True).start()

    def get_device_id(self, ip):
        try:
            res = requests.get(f"http://{ip}:8090/info", timeout=5)
            if res.status_code == 200:
                root = ET.fromstring(res.text)
                return root.attrib.get('deviceID')
        except Exception as e:
            self.log(f"Could not fetch DeviceID for {ip}: {e}", "ERROR")
        return None

    def sync_zone(self):
        master_ip = self.master_combo.get()
        selected_indices = self.slave_listbox.curselection()
        slave_ips = [self.slave_listbox.get(i) for i in selected_indices]
        if not master_ip or not slave_ips:
            self.log("Sync failed: Selection missing", "ERROR")
            return
        final_slaves = [s for s in slave_ips if s != master_ip]
        if not final_slaves:
            self.log("Sync failed: Master cannot be slave", "ERROR")
            return

        master_id = self.get_device_id(master_ip)
        if not master_id:
            self.log("Sync failed: Could not get Master DeviceID", "ERROR")
            return

        # STRATEGY 1: The "Gabbo" Standard (Most likely to bypass 1019)
        self.log("Trial 1: Testing 'Gabbo' sender attribute...")
        slave_xml = "".join([f'<member ipaddress="{s}">{self.get_device_id(s)}</member>' for s in final_slaves])
        payload1 = f'<zone master="{master_id}" sender="Gabbo">{slave_xml}</zone>'
        if self._attempt_sync(master_ip, payload1): return

        # STRATEGY 2: The "Binary-Gabbo" Hybrid (Combining PCAP header + Gabbo)
        self.log("Trial 2: Testing Binary Header + Gabbo...")
        binary_header = bytes([0x00, 0x00, 0x00, 0x08, 0x01, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00])
        payload2 = binary_header + payload1.encode('utf-8')
        if self._attempt_sync(master_ip, payload2): return

        # STRATEGY 3: The "Member" Format (Found in OpenAPI spec)
        self.log("Trial 3: Testing Member Format...")
        payload3 = f'<zone master="{master_id}">{slave_xml}</zone>'
        if self._attempt_sync(master_ip, payload3): return

        self.log("All sync strategies failed. Still receiving CLIENT_XML_ERROR.", "ERROR")

    def _attempt_sync(self, master_ip, payload):
        try:
            res = requests.post(f"http://{master_ip}:8090/setZone", 
                                data=payload, 
                                headers={'Content-Type': 'text/xml'}, 
                                timeout=5)
            time.sleep(1)
            v_res = requests.get(f"http://{master_ip}:8090/getZone", timeout=5)
            if v_res.status_code == 200:
                root = ET.fromstring(v_res.text)
                # Check if any member is present in the returned zone
                found_slaves = [s.attrib.get('ip') or s.text for s in root.findall(".//member") or root.findall(".//slave")]
                if found_slaves:
                    self.log(f"SUCCESS: Sync verified!", "SUCCESS")
                    self.root.after(0, lambda: messagebox.showinfo("Success", "Zone verified and active!"))
                    return True
            self.log(f"Attempt failed. Status: {res.status_code}", "ERROR")
        except Exception as e:
            self.log(f"Network error: {e}", "ERROR")
        return False

    def verify_zone(self):
        master = self.master_combo.get()
        if not master:
            messagebox.showwarning("Error", "Select a Master speaker first.")
            return
        self.log(f"Verifying zone on Master {master}...")
        def run_verify():
            try:
                res = requests.get(f"http://{master}:8090/getZone", timeout=5)
                if res.status_code == 200:
                    root = ET.fromstring(res.text)
                    slaves = root.findall(".//member") or root.findall(".//slave")
                    slave_list = [s.attrib.get('ip') or s.text for s in slaves]
                    if not slave_list:
                        self.log("Master reports NO slaves in the zone.", "ERROR")
                        self.root.after(0, lambda: messagebox.showinfo("Zone Status", "No slaves found in this zone."))
                    else:
                        self.log(f"Master reports {len(slave_list)} slaves: {', '.join(slave_list)}", "SUCCESS")
                        self.root.after(0, lambda: messagebox.showinfo("Zone Status", f"Current Zone Members:\\n\\nMaster: {master}\\nSlaves: {', '.join(slave_list)}"))
                else:
                    self.log(f"Verify failed. Status: {res.status_code}", "ERROR")
            except Exception as e:
                self.log(f"Verification error: {e}", "ERROR")
        threading.Thread(target=run_verify, daemon=True).start()

    def clear_zone(self):
        master = self.master_combo.get()
        if not master: return
        payload = '<zone masterid=""></zone>'
        try:
            res = requests.post(f"http://{master}:8090/setZone", data=payload, headers={'Content-Type': 'text/xml'}, timeout=5)
            if res.status_code == 200:
                self.log("Zone cleared successfully.", "SUCCESS")
                messagebox.showinfo("Success", "Zone cleared.")
        except Exception as e:
            self.log(f"Clear failed: {e}", "ERROR")

    def build_danger_tab(self):
        frame = ttk.Frame(self.tab_danger, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        warning_f = ttk.Frame(frame)
        warning_f.pack(pady=20)
        ttk.Label(warning_f, text="WARNING: FACTORY RESET", font=("Arial", 14, "bold"), foreground="red").pack(pady=10)
        ttk.Label(warning_f, text="This will wipe all Wi-Fi settings, presets, and paired devices.\\n"
                                 "The speaker will reboot into Setup Mode.", wraplength=400, justify=tk.CENTER).pack(pady=10)
        self.add_reset_links(warning_f, target_tab=self.tab_setup)
        ttk.Button(frame, text="⚠️ FACTORY RESET SELECTED SPEAKER", command=self.factory_reset).pack(pady=20)

if __name__ == "__main__":
    root = tk.Tk()
    app = BoseQuadManager(root)
    root.mainloop()