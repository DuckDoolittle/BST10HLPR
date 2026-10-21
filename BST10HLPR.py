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

class BoseMultiZoneManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Bose SoundTouch Multi-Zone Manager")
        self.root.geometry("900x950")
        self.config_path = os.path.expanduser("~/.bose_manager_config.json")
        
        # State
        self.discovered_speakers = {} 
        self.selected_speaker_ip = tk.StringVar()
        self.is_open_network = tk.BooleanVar(value=False)
        
        # Zones State: { zone_id: {"master": ip, "slaves": [ips]} }
        self.zones = { "Zone 1": {"master": "", "slaves": []} }
        self.active_zone_id = tk.StringVar(value="Zone 1")

        self.load_settings()
        self.setup_ui()

    def load_settings(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    self.discovered_speakers = data.get("speakers", {})
                    self.zones = data.get("zones", { "Zone 1": {"master": "", "slaves": []} })
                    last_ip = data.get("last_selected_ip", "")
                    self.selected_speaker_ip.set(last_ip)
            except Exception as e: print(f"Error loading config: {e}")

    def save_settings(self):
        data = {
            "speakers": self.discovered_speakers, 
            "last_selected_ip": self.selected_speaker_ip.get(),
            "zones": self.zones
        }
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
        
        self.log("Application started. Support for up to 20 speakers and 5 zones active.")
        self.update_speaker_lists()

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
        
        top_f = ttk.Frame(frame)
        top_f.pack(fill=tk.X, pady=10)
        ttk.Label(top_f, text="Zone Management", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(top_f, text="➕ Add Zone", command=self.add_zone_ui).pack(side=tk.RIGHT)
        
        self.zone_container = ttk.Frame(frame)
        self.zone_container.pack(fill=tk.BOTH, expand=True)
        
        self.refresh_zones_ui()

    def add_zone_ui(self):
        if len(self.zones) >= 5:
            messagebox.showwarning("Limit Reached", "Maximum of 5 zones allowed.")
            return
        
        zone_id = f"Zone {len(self.zones) + 1}"
        self.zones[zone_id] = {"master": "", "slaves": []}
        self.save_settings()
        self.refresh_zones_ui()
        self.log(f"Added {zone_id}", "SUCCESS")

    def delete_zone(self, zone_id):
        if len(self.zones) <= 1:
            messagebox.showwarning("Constraint", "At least one zone must always exist.")
            return
        if messagebox.askyesno("Confirm", f"Delete {zone_id}?"):
            del self.zones[zone_id]
            self.save_settings()
            self.refresh_zones_ui()
            self.log(f"Deleted {zone_id}", "SUCCESS")

    def refresh_zones_ui(self):
        for widget in self.zone_container.winfo_children():
            widget.destroy()
            
        for zone_id, data in self.zones.items():
            z_frame = ttk.LabelFrame(self.zone_container, text=f" {zone_id} ", padding="10")
            z_frame.pack(fill=tk.X, pady=5, padx=5)
            
            # Row 1: Master selection
            row1 = ttk.Frame(z_frame)
            row1.pack(fill=tk.X)
            ttk.Label(row1, text="Master:").pack(side=tk.LEFT)
            m_combo = ttk.Combobox(row1, state="readonly", values=list(self.discovered_speakers.keys()))
            m_combo.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
            m_combo.set(data["master"])
            
            # Row 2: Slaves
            row2 = ttk.Frame(z_frame)
            row2.pack(fill=tk.X, pady=5)
            ttk.Label(row2, text="Slaves:").pack(side=tk.LEFT)
            s_list = tk.Listbox(row2, selectmode=tk.MULTIPLE, height=3)
            s_list.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
            
            # Logic to populate slaves excluding the current master
            def populate_slaves(master_ip, listbox, zone_data):
                listbox.delete(0, tk.END)
                current_slaves = zone_data.get("slaves", [])
                for ip in list(self.discovered_speakers.keys()):
                    if ip != master_ip:
                        listbox.insert(tk.END, ip)
                # Restore selection
                for i in range(listbox.size()):
                    if listbox.get(i) in current_slaves:
                        listbox.selection_set(i)

            populate_slaves(data["master"], s_list, data)

            # Update master and refresh slave list on change
            def on_master_change(e, zid=zone_id, cb=m_combo, lb=s_list):
                new_master = cb.get()
                self.update_zone_data(zid, "master", new_master)
                populate_slaves(new_master, lb, self.zones[zid])

            m_combo.bind("<<ComboboxSelected>>", on_master_change)
            
            # Row 3: Buttons
            row3 = ttk.Frame(z_frame)
            row3.pack(fill=tk.X)
            ttk.Button(row3, text="🚀 Sync Zone", 
                       command=lambda zid=zone_id, cb=m_combo, lb=s_list: self.start_sync_thread(zid, cb, lb)).pack(side=tk.LEFT, padx=5)
            ttk.Button(row3, text="🔍 Verify", 
                       command=lambda zid=zone_id, cb=m_combo: self.verify_zone(cb.get())).pack(side=tk.LEFT, padx=5)
            
            if zone_id != "Zone 1" or len(self.zones) > 1:
                ttk.Button(row3, text="❌ Delete Zone", 
                           command=lambda zid=zone_id: self.delete_zone(zid)).pack(side=tk.RIGHT, padx=5)

    def update_zone_data(self, zone_id, field, value):
        self.zones[zone_id][field] = value
        self.save_settings()

    def start_sync_thread(self, zone_id, master_combo, slave_listbox):
        master_ip = master_combo.get()
        selected_indices = slave_listbox.curselection()
        slave_ips = [slave_listbox.get(i) for i in selected_indices]
        threading.Thread(target=self.sync_zone, args=(zone_id, master_ip, slave_ips), daemon=True).start()

    def get_device_id(self, ip):
        try:
            res = requests.get(f"http://{ip}:8090/info", timeout=5)
            if res.status_code == 200:
                root = ET.fromstring(res.text)
                return root.attrib.get('deviceID')
        except Exception as e: self.log(f"Could not fetch DeviceID for {ip}: {e}", "ERROR")
        return None

    def sync_zone(self, zone_id, master_ip, slave_ips):
        if not master_ip or not slave_ips:
            self.log(f"Sync failed for {zone_id}: Selection missing", "ERROR")
            return
        final_slaves = [s for s in slave_ips if s != master_ip]
        if not final_slaves:
            self.log(f"Sync failed for {zone_id}: Master cannot be slave", "ERROR")
            return

        master_id = self.get_device_id(master_ip)
        if not master_id:
            self.log(f"Sync failed for {zone_id}: Could not get Master DeviceID", "ERROR")
            return

        # Implementation of the "Gabbo" success pattern
        self.log(f"Syncing {zone_id} with 'Gabbo' sender...")
        slave_xml = "".join([f'<member ipaddress="{s}">{self.get_device_id(s)}</member>' for s in final_slaves])
        payload = f'<zone master="{master_id}" sender="Gabbo">{slave_xml}</zone>'
        
        try:
            res = requests.post(f"http://{master_ip}:8090/setZone", 
                                data=payload, 
                                headers={'Content-Type': 'text/xml'}, 
                                timeout=5)
            time.sleep(1)
            v_res = requests.get(f"http://{master_ip}:8090/getZone", timeout=5)
            if v_res.status_code == 200:
                root = ET.fromstring(v_res.text)
                found_slaves = [s.attrib.get('ip') or s.text for s in root.findall(".//member") or root.findall(".//slave")]
                if found_slaves:
                    self.zones[zone_id]["master"] = master_ip
                    self.zones[zone_id]["slaves"] = final_slaves
                    self.save_settings()
                    self.log(f"SUCCESS: {zone_id} verified!", "SUCCESS")
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"{zone_id} is now active!"))
                    return
            self.log(f"Sync failed for {zone_id}. Status: {res.status_code}", "ERROR")
        except Exception as e:
            self.log(f"Network error during {zone_id} sync: {e}", "ERROR")

    def verify_zone(self, master):
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
                        self.log("Master reports NO slaves.", "ERROR")
                        self.root.after(0, lambda: messagebox.showinfo("Zone Status", "No slaves found in this zone."))
                    else:
                        self.log(f"Master reports {len(slave_list)} slaves: {', '.join(slave_list)}", "SUCCESS")
                        self.root.after(0, lambda: messagebox.showinfo("Zone Status", f"Zone Members:\\n\\nMaster: {master}\\nSlaves: {', '.join(slave_list)}"))
                else: self.log(f"Verify failed. Status: {res.status_code}", "ERROR")
            except Exception as e: self.log(f"Verification error: {e}", "ERROR")
        threading.Thread(target=run_verify, daemon=True).start()

    def clear_zone(self):
        # In the multi-zone version, this is handled by Delete Zone.
        # But we can keep a global clear for the selected master.
        master = self.selected_speaker_ip.get()
        if not master: return
        payload = '<zone masterid=""></zone>'
        try:
            res = requests.post(f"http://{master}:8090/setZone", data=payload, headers={'Content-Type': 'text/xml'}, timeout=5)
            if res.status_code == 200:
                self.log("Zone cleared successfully.", "SUCCESS")
                messagebox.showinfo("Success", "Zone cleared.")
        except Exception as e: self.log(f"Clear failed: {e}", "ERROR")

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
    app = BoseMultiZoneManager(root)
    root.mainloop()
