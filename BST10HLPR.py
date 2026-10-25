#!/usr/bin/env python3
"""
Bose SoundTouch Quad-Manager v5
-------------------------------
Theme notes for KDE / Kubuntu:
  * The default Tk theme on KDE discards most ttk colour options, which is why
    LabelFrames / Entries stayed light grey. We force the 'clam' theme, which
    honours background, fieldbackground, bordercolor, troughcolor, etc.
  * ttk.Notebook has NO '-background' option (that is a plain-Tk option only).
    Notebook colours are set through the style, never via .configure().
  * Combobox drop-down lists are plain Tk Listboxes, styled via option_add().

Session persistence:
  Everything is written to ~/.bose_manager_config.json:
    speakers          -> every IP ever seen, with its label
    forgotten         -> IPs you explicitly removed (hidden from all lists)
    zone_slaves       -> contents of the Zone Management listbox
    zone_selection    -> which rows were highlighted
    last_selected_ip  -> active speaker in the Control Center
    master_ip         -> master speaker in Zone Management
    dark_mode         -> theme
    window_geometry   -> size and position
  Saved on every change, and again on window close (WM_DELETE_WINDOW).

FIXES FROM V4 TO V5:
  * TRUE deletion: speakers can now be permanently removed from the config.
    Previously "Forget" only hid an IP while it stayed in the speakers map,
    and "Clear All Forgotten" deleted the hide-list, which resurrected the
    entries on the next launch. Removal now purges the IP from EVERY store.
  * New "Remove Permanently" action in the Forgotten Speakers tab.
  * New "Remove" button (true delete) beside Forget in the Control Center.
  * Startup no longer auto-resurrects known IPs: only entries in the
    speakers map are shown, and nothing is re-added implicitly.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
import socket
import threading
import json
import os
import re
from datetime import datetime
import xml.etree.ElementTree as ET
import webbrowser
import time
import fcntl
import struct
import ipaddress
from concurrent.futures import ThreadPoolExecutor
import select


GEOMETRY_RE = re.compile(r"^\d+x\d+([+-]\d+[+-]\d+)?$")


class BoseQuadManager:
    def __init__(self, root):
        self.root = root
        self.root.title("BST10HLPR v5")
        self.root.geometry("800x900")
        self.config_path = os.path.expanduser("~/.bose_manager_config.json")

        # ---------------------------------------------------------- state
        self.discovered_speakers = {}   # ip -> label
        self.forgotten_ips = set()      # hidden from every list until restored
        self.zone_slaves = []           # contents of the Zone Management listbox
        self.zone_selection = []        # highlighted rows in that listbox
        self.master_ip = ""             # master speaker in Zone Management
        self._saved_geometry = None

        self.selected_speaker_ip = tk.StringVar()
        self.is_open_network = tk.BooleanVar(value=False)
        self.dark_mode = tk.BooleanVar(value=True)

        # Plain Tk widgets that need direct (non-style) recolouring
        self.listboxes = []
        self.link_labels = []

        # IOCTL constants for iface enumeration
        self.SIOCGIFADDR    = 0x8915
        self.SIOCGIFNETMASK = 0x891b
        self.SIOCGIFFLAGS   = 0x8913
        self.IFF_UP         = 0x1
        self.IFF_LOOPBACK   = 0x8

        self.load_settings()
        self.setup_ui()
        self.restore_window_state()
        # Apply theme last so it wins over widget construction defaults
        self.toggle_theme()

        # Make sure a normal window close writes the session out
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ config
    def load_settings(self):
        """Read the previous session. Tolerates older/minimal config files."""
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return

        self.discovered_speakers = data.get("speakers", {}) or {}
        self.forgotten_ips = set(data.get("forgotten", []) or [])
        self.zone_slaves = list(data.get("zone_slaves", []) or [])
        self.zone_selection = [int(i) for i in (data.get("zone_selection", []) or [])
                               if str(i).isdigit()]
        self.selected_speaker_ip.set(data.get("last_selected_ip", "") or "")
        self.master_ip = data.get("master_ip", "") or ""

        if "dark_mode" in data:
            self.dark_mode.set(bool(data["dark_mode"]))

        geo = data.get("window_geometry")
        if isinstance(geo, str) and GEOMETRY_RE.match(geo):
            self._saved_geometry = geo

    def save_settings(self):
        """Write the whole session out. Called on every change and on exit."""
        geometry = None
        try:
            candidate = self.root.winfo_geometry()
            # Ignore the bogus 1x1+0+0 reported before the window is mapped
            if GEOMETRY_RE.match(candidate) and not candidate.startswith("1x1"):
                geometry = candidate
        except tk.TclError:
            pass

        master = ""
        if hasattr(self, 'master_combo'):
            master = self.master_combo.get()
        elif self.master_ip:
            master = self.master_ip

        data = {
            "speakers": self.discovered_speakers,
            "forgotten": sorted(self.forgotten_ips),
            "zone_slaves": [ip for ip in self.zone_slaves
                            if ip in self.discovered_speakers],
            "zone_selection": list(self.zone_selection),
            "last_selected_ip": self.selected_speaker_ip.get()
                                if self.selected_speaker_ip.get()
                                in self.discovered_speakers else "",
            "master_ip": master if master in self.discovered_speakers else "",
            "dark_mode": bool(self.dark_mode.get()),
            "window_geometry": geometry or self._saved_geometry,
        }
        try:
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

    def on_close(self):
        """Persist the session, then quit."""
        try:
            self.save_settings()
        finally:
            self.root.destroy()

    def restore_window_state(self):
        """Reapply geometry, highlighted rows and report what was restored."""
        if self._saved_geometry:
            try:
                self.root.geometry(self._saved_geometry)
            except tk.TclError:
                pass

        if hasattr(self, 'slave_listbox') and self.zone_selection:
            self.slave_listbox.selection_clear(0, tk.END)
            size = self.slave_listbox.size()
            for idx in self.zone_selection:
                if 0 <= idx < size:
                    self.slave_listbox.selection_set(idx)

        if self.discovered_speakers:
            self.log(f"Restored session: {len(self.discovered_speakers)} known speaker(s), "
                     f"{len(self.zone_slaves)} in zone list, "
                     f"{len(self.forgotten_ips)} forgotten.", "INFO")

    # --------------------------------------------------------------------- log
    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = f"[{level}]"
        formatted_msg = f"{timestamp} {tag: <10} {message}\n"
        self.root.after(0, self._write_to_log, formatted_msg)

    def _write_to_log(self, msg):
        self.log_panel.insert(tk.END, msg)
        self.log_panel.see(tk.END)

    # ---------------------------------------------------------------------- ui
    def setup_ui(self):
        self.style = ttk.Style()

        # THE key line: 'clam' honours colour options, the KDE default theme
        # silently ignores most of them.
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        # Header frame holding the theme toggle
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill=tk.X, padx=10, pady=5)

        self.theme_toggle = ttk.Checkbutton(header_frame, text="🌙 Dark Mode",
                                            variable=self.dark_mode,
                                            command=self.toggle_theme)
        self.theme_toggle.pack(side=tk.RIGHT)

        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)

        self.tabControl = ttk.Notebook(main_container)
        self.tabControl.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tab_setup = ttk.Frame(self.tabControl)
        self.tab_control = ttk.Frame(self.tabControl)
        self.tab_pairing = ttk.Frame(self.tabControl)
        self.tab_forgotten = ttk.Frame(self.tabControl)
        self.tab_danger = ttk.Frame(self.tabControl)

        self.tabControl.add(self.tab_setup, text=' 🛠️ Initial Setup ')
        self.tabControl.add(self.tab_control, text=' 🔊 Control Center ')
        self.tabControl.add(self.tab_pairing, text=' 👯 Zone Management ')
        self.tabControl.add(self.tab_forgotten, text=' 🗂️ Forgotten Speakers ')
        self.tabControl.add(self.tab_danger, text=' ⚠️ Danger Zone ')

        self.build_setup_tab()
        self.build_control_tab()
        self.build_pairing_tab()
        self.build_forgotten_tab()
        self.build_danger_tab()

        log_frame = ttk.LabelFrame(main_container, text=" Event Log ", padding="10")
        log_frame.pack(fill=tk.X, padx=10, pady=10)

        self.log_panel = scrolledtext.ScrolledText(log_frame, height=12,
                                                   font=("Consolas", 9),
                                                   wrap="word")
        self.log_panel.pack(fill=tk.X)

        self.log("Application started.")
        self.update_speaker_lists()

    # ------------------------------------------------------------------- theme
    def toggle_theme(self):
        """Recolour every widget. Works because the 'clam' theme is active."""
        if self.dark_mode.get():
            bg = "#1e1e1e"          # window / frame background
            fg = "#dcdcdc"          # text
            accent = "#2a2a2a"      # buttons, tabs, scrollbar thumbs
            border = "#3a3a3a"      # visible borders
            field = "#2a2a2a"       # entry / text / list backgrounds
            sel_bg, sel_fg = "#4a90d9", "#ffffff"
            link = "#6fa8ff"
            danger = "#ff6b6b"
        else:
            bg = "#f0f0f0"
            fg = "#000000"
            accent = "#e1e1e1"
            border = "#b8b8b8"
            field = "#ffffff"
            sel_bg, sel_fg = "#4a90d9", "#ffffff"
            link = "#6fa8ff"
            danger = "#c00000"

        self.root.configure(bg=bg)
        s = self.style

        # --- containers and labels -------------------------------------------
        s.configure("TFrame", background=bg)
        s.configure("TLabel", background=bg, foreground=fg)

        # --- checkbox ---------------------------------------------------------
        s.configure("TCheckbutton", background=bg, foreground=fg,
                    indicatorcolor=field, focuscolor=bg)
        s.map("TCheckbutton",
              background=[("active", bg)],
              foreground=[("disabled", "#808080")])

        # --- buttons ----------------------------------------------------------
        s.configure("TButton", background=accent, foreground=fg,
                    bordercolor=border, lightcolor=accent, darkcolor=accent,
                    focuscolor=accent, relief="flat", padding=(8, 4))
        s.map("TButton",
              background=[("pressed", border), ("active", border)],
              foreground=[("disabled", "#808080")])

        # --- entries ----------------------------------------------------------
        s.configure("TEntry", fieldbackground=field, foreground=fg,
                    bordercolor=border, lightcolor=border, darkcolor=border,
                    insertcolor=fg, padding=2)
        s.map("TEntry",
              fieldbackground=[("disabled", bg), ("readonly", field)],
              foreground=[("disabled", "#808080")])

        # --- comboboxes -------------------------------------------------------
        s.configure("TCombobox", fieldbackground=field, background=accent,
                    foreground=fg, arrowcolor=fg, bordercolor=border,
                    lightcolor=border, darkcolor=border, padding=2)
        s.map("TCombobox",
              fieldbackground=[("readonly", field), ("disabled", bg)],
              foreground=[("readonly", fg), ("disabled", "#808080")],
              background=[("readonly", accent)],
              arrowcolor=[("disabled", "#808080")])

        # --- labelled frames (the boxes that stayed light grey) ---------------
        s.configure("TLabelframe", background=bg, bordercolor=border,
                    lightcolor=border, darkcolor=border,
                    relief="solid", borderwidth=1)
        s.configure("TLabelframe.Label", background=bg, foreground=fg)

        # --- notebook ---------------------------------------------------------
        s.configure("TNotebook", background=bg, bordercolor=border,
                    lightcolor=border, darkcolor=border,
                    tabmargins=(2, 5, 2, 0))
        s.configure("TNotebook.Tab", background=accent, foreground=fg,
                    bordercolor=border, lightcolor=border, darkcolor=border,
                    padding=(12, 5))
        s.map("TNotebook.Tab",
              background=[("selected", bg)],
              foreground=[("selected", fg)])

        # --- ttk scrollbars ---------------------------------------------------
        for orient in ("Vertical", "Horizontal"):
            s.configure(f"{orient}.TScrollbar",
                        background=accent, troughcolor=bg, bordercolor=border,
                        arrowcolor=fg, lightcolor=accent, darkcolor=accent)

        # --- combobox drop-down lists (plain Tk Listboxes) --------------------
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", fg)
        self.root.option_add("*TCombobox*Listbox.selectBackground", sel_bg)
        self.root.option_add("*TCombobox*Listbox.selectForeground", sel_fg)

        # --- plain Tk ScrolledText + its scrollbars ---------------------------
        self.log_panel.configure(bg=field, fg=fg, insertbackground=fg,
                                 selectbackground=sel_bg, selectforeground=sel_fg,
                                 highlightthickness=0, borderwidth=0,
                                 relief="flat")
        for bar in (getattr(self.log_panel, "vbar", None),
                    getattr(self.log_panel, "hbar", None)):
            if bar is not None:
                bar.configure(bg=accent, troughcolor=bg, activebackground=border,
                              highlightthickness=0, borderwidth=0, relief="flat")

        # --- plain Tk Listbox (slave speaker picker) --------------------------
        for lb in self.listboxes:
            lb.configure(bg=field, fg=fg, selectbackground=sel_bg,
                         selectforeground=sel_fg, highlightthickness=0,
                         borderwidth=1, relief="solid", activestyle="none")

        # --- link labels and the red warning heading --------------------------
        for lbl in self.link_labels:
            try:
                lbl.configure(foreground=link)
            except tk.TclError:
                pass
        try:
            self.danger_label.configure(foreground=danger)
        except (AttributeError, tk.TclError):
            pass

        # Remember the choice straight away, not just on exit
        self.save_settings()

    # ------------------------------------------------------------------- tabs
    def add_reset_links(self, parent_frame, target_tab=None):
        link_frame = ttk.Frame(parent_frame)
        link_frame.pack(pady=10)

        st10_link = ttk.Label(link_frame, text="SoundTouch 10 Reset",
                              cursor="hand2")
        st10_link.pack(pady=2)
        st10_link.bind("<Button-1>", lambda e: webbrowser.open(
            "https://support.bose.com/article/soundtouch-10-resetting-your-product"))

        wifi_link = ttk.Label(link_frame, text="Access Local Wi-Fi (Setup Mode)",
                              cursor="hand2")
        wifi_link.pack(pady=2)
        wifi_link.bind("<Button-1>", lambda e: webbrowser.open(
            "https://support.bose.com/article/soundtouch-10-connecting-to-a-wi-fi-network"))

        other_link = ttk.Label(link_frame, text="Other Models", cursor="hand2")
        other_link.pack(pady=2)
        other_link.bind("<Button-1>", lambda e: webbrowser.open("https://support.bose.com/"))

        self.link_labels.extend([st10_link, wifi_link, other_link])

        if target_tab:
            nav_text = "Go to Initial Setup" if target_tab == self.tab_setup else "Go to Setup Tab"
            setup_link = ttk.Label(link_frame, text=nav_text, cursor="hand2")
            setup_link.pack(pady=10)
            setup_link.bind("<Button-1>", lambda e: self.tabControl.select(target_tab))
            self.link_labels.append(setup_link)

        return link_frame

    def build_setup_tab(self):
        frame = ttk.Frame(self.tab_setup, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        instr = ("For each new speaker:\n1. Hold '2' and 'Volume -' until LED is amber.\n"
                 "2. Connect Ubuntu Wi-Fi to 'Bose SoundTouch XXXX'.\n"
                 "3. Enter your home Wi-Fi details and click 'Join Wi-Fi'.")
        info_label = ttk.Label(frame, text=instr, wraplength=500, justify=tk.LEFT)
        info_label.pack(pady=10)
        self.link_labels.append(info_label)

        self.add_reset_links(frame)

        input_f = ttk.Frame(frame, padding="10")
        input_f.pack(pady=20)

        ttk.Label(input_f, text="Home SSID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.setup_ssid = ttk.Entry(input_f, width=30)
        self.setup_ssid.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(input_f, text="Home Password:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.setup_pass = ttk.Entry(input_f, show="*", width=30)
        self.setup_pass.grid(row=1, column=1, padx=5, pady=5)

        self.open_net_check = ttk.Checkbutton(input_f,
                                              text="Network is Open (No Password)",
                                              variable=self.is_open_network,
                                              command=self.toggle_pass_field)
        self.open_net_check.grid(row=2, column=0, columnspan=2, pady=10, sticky=tk.W)

        ttk.Button(frame, text="Join Wi-Fi", command=self.provision_wifi).pack(pady=10)

    def toggle_pass_field(self):
        self.setup_pass.config(state="disabled" if self.is_open_network.get() else "normal")

    def provision_wifi(self):
        ssid = self.setup_ssid.get().strip()
        if not ssid:
            return
        sec_type = "none" if self.is_open_network.get() else "wpa_or_wpa2"
        pw = "" if self.is_open_network.get() else self.setup_pass.get().strip()
        try:
            requests.post("http://192.0.2.1:8090/performWirelessSiteSurvey",
                          data='<PerformWirelessSiteSurvey timeout="5"/>', timeout=5)
            payload = (f'<AddWirelessProfile><profile ssid="{ssid}" password="{pw}" '
                       f'securityType="{sec_type}" /></AddWirelessProfile>')
            res = requests.post("http://192.0.2.1:8090/addWirelessProfile",
                                data=payload, timeout=10)
            if res.status_code == 200:
                messagebox.showinfo("Success", "Credentials sent!")
        except Exception as e:
            messagebox.showerror("Error", f"Provisioning failed: {e}")

    def build_control_tab(self):
        frame = ttk.Frame(self.tab_control, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        select_f = ttk.LabelFrame(frame, text="Device Selection", padding="10")
        select_f.pack(fill=tk.X, pady=10)

        # Top row: Speaker combo + Scan/Forget/Remove buttons
        top_row = ttk.Frame(select_f)
        top_row.pack(fill=tk.X)

        left_col = ttk.Frame(top_row)
        left_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(left_col, text="Active Speaker:").pack(side=tk.LEFT)
        self.speaker_combo = ttk.Combobox(left_col, textvariable=self.selected_speaker_ip,
                                          state="readonly", width=25)
        self.speaker_combo.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        self.speaker_combo.bind("<<ComboboxSelected>>", lambda e: self.save_settings())

        right_col = ttk.Frame(top_row)
        right_col.pack(side=tk.RIGHT)
        ttk.Button(right_col, text="🔍 Find Speakers", command=self.start_combined_scan).pack(side=tk.LEFT, padx=2)
        ttk.Button(right_col, text="🗑️ Forget", command=self.forget_ip).pack(side=tk.LEFT, padx=2)

        # Bottom row: Manual IP entry + Add/Sweep buttons
        bottom_row = ttk.Frame(select_f)
        bottom_row.pack(fill=tk.X, pady=10)

        ip_input_f = ttk.Frame(bottom_row)
        ip_input_f.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(ip_input_f, text="Add Manual IP:").pack(side=tk.LEFT)
        self.manual_ip = ttk.Entry(ip_input_f, width=20)
        self.manual_ip.pack(side=tk.LEFT, padx=10)

        btn_f = ttk.Frame(bottom_row)
        btn_f.pack(side=tk.LEFT)
        ttk.Button(btn_f, text="Add", command=self.add_manual_ip).pack(side=tk.LEFT, padx=2)


    def add_manual_ip(self):
        """Add an IP by hand. Also un-forgets it, so it is a way back in."""
        ip = self.manual_ip.get().strip()
        if not ip:
            self.log("Manual IP entry is empty.", "WARN")
            return

        # Validate basic IP format
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(ip_pattern, ip):
            messagebox.showwarning("Invalid IP",
                                   f"'{ip}' doesn't look like a valid IP address.\n"
                                   "Expected format: 192.168.x.x")
            return

        self.discovered_speakers[ip] = "Manually Added"
        if ip in self.forgotten_ips:
            self.forgotten_ips.discard(ip)
            self.log(f"{ip} was previously forgotten - restored to all lists.", "INFO")
        if ip not in self.zone_slaves:
            self.zone_slaves.append(ip)
        self.manual_ip.delete(0, tk.END)
        self.update_speaker_lists()
        self.refresh_forgotten_tab()
        self.save_settings()
        self.log(f"Manually added speaker {ip}", "SUCCESS")

        # Auto-select the newly added speaker
        self.speaker_combo.set(ip)
        self.selected_speaker_ip.set(ip)

    # ----------------------------------------------------------- true removal
    def _purge_ip_everywhere(self, ip):
        """Fully delete an IP from every persisted store."""
        self.discovered_speakers.pop(ip, None)
        self.forgotten_ips.discard(ip)
        if ip in self.zone_slaves:
            self.zone_slaves.remove(ip)
        if self.master_ip == ip:
            self.master_ip = ""
        if self.selected_speaker_ip.get() == ip:
            self.selected_speaker_ip.set("")

    def remove_ip_permanently(self):
        """Delete the active speaker from the config entirely. Stays gone
        across restarts until it is re-discovered or re-added manually."""
        ip = self.selected_speaker_ip.get()
        if not ip:
            messagebox.showwarning("Error", "Please select a speaker from the list first.")
            return

        if messagebox.askyesno("Confirm",
                               f"PERMANENTLY REMOVE {ip}?\n\n"
                               "Unlike Forget, this erases the IP from the saved "
                               "config completely. It will NOT come back on the "
                               "next launch. It can only reappear if a scan "
                               "finds it again or you add it manually."):
            self._purge_ip_everywhere(ip)
            self.speaker_combo.set("")
            self.update_speaker_lists()
            self.refresh_forgotten_tab()
            self.save_settings()
            self.log(f"Permanently removed {ip} from saved config", "SUCCESS")

    def remove_selected_permanently(self):
        """Delete highlighted rows in the Forgotten tab from the config entirely."""
        if not hasattr(self, 'forgotten_listbox'):
            return
        selected_indices = self.forgotten_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Error", "Please select one or more entries to remove.")
            return

        ips = [self.forgotten_listbox.get(idx).split('(')[0].strip()
               for idx in selected_indices]
        listing = "\n".join(f"  • {ip}" for ip in ips)

        if messagebox.askyesno("Confirm",
                               f"PERMANENTLY REMOVE {len(ips)} speaker record(s)?\n\n"
                               f"{listing}\n\n"
                               "They are erased from the saved config completely "
                               "and will not come back on the next launch."):
            for ip in ips:
                self._purge_ip_everywhere(ip)
            self.update_speaker_lists()
            self.refresh_forgotten_tab()
            self.save_settings()
            self.log(f"Permanently removed {len(ips)} speaker record(s)", "SUCCESS")

    def purge_all_records(self):
        """Wipe every speaker record, forgotten entry and zone entry."""
        total = len(self.discovered_speakers)
        if total == 0:
            messagebox.showinfo("Info", "Nothing to remove - no saved records.")
            return

        if messagebox.askyesno("Confirm",
                               f"DELETE ALL {total} saved speaker record(s)?\n\n"
                               "Every IP is erased from the config: known list, "
                               "forgotten list, and zone list. This cannot be "
                               "undone - a fresh scan or manual entry is needed "
                               "to bring anything back."):
            self.discovered_speakers.clear()
            self.forgotten_ips.clear()
            self.zone_slaves = []
            self.zone_selection = []
            self.master_ip = ""
            self.selected_speaker_ip.set("")
            self.speaker_combo.set("")
            self.update_speaker_lists()
            self.refresh_forgotten_tab()
            self.save_settings()
            self.log(f"Purged all {total} speaker record(s) from config", "SUCCESS")

    # --------------------------------------------------------------- playback
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
        # To control volume across a synchronised zone, send the command to the
        # Master. Most SoundTouch models propagate /setVolume to slaves.
        payload = f'<?xml version="1.0" encoding="UTF-8"?><setVolume value="{value}" />'
        try:
            res = requests.post(f"http://{ip}:8090/setVolume", data=payload, timeout=2)
            if res.status_code == 200:
                self.log(f"Volume set to {value} on {ip}", "SUCCESS")
                return
        except Exception as e:
            self.log(f"Volume set failed: {e}", "ERROR")

        # Fallback: GET request
        try:
            res = requests.get(f"http://{ip}:8090/setVolume?value={value}", timeout=2)
            if res.status_code == 200:
                self.log(f"Volume set to {value} (GET) on {ip}", "SUCCESS")
                return
        except Exception:
            pass

    # ---------------------------------------------------------------- forgetting
    def forget_ip(self):
        """Forget the active speaker everywhere. Persisted across restarts."""
        ip = self.selected_speaker_ip.get()
        if not ip:
            messagebox.showwarning("Error", "Please select a speaker from the list first.")
            return

        if messagebox.askyesno("Confirm",
                               f"Forget speaker at {ip}?\n\n"
                               "It stays hidden after restarting. Use the "
                               "'Forgotten Speakers' tab to restore it, or "
                               "'Remove' to erase it permanently."):
            self.forgotten_ips.add(ip)
            if ip in self.zone_slaves:
                self.zone_slaves.remove(ip)
            self.selected_speaker_ip.set("")
            self.speaker_combo.set("")
            self.update_speaker_lists()
            self.refresh_forgotten_tab()
            self.save_settings()
            self.log(f"Forgotten speaker at {ip} (saved)", "SUCCESS")

    def forget_slave(self):
        """Remove highlighted rows from the zone list, permanently."""
        if not hasattr(self, 'slave_listbox'):
            self.log("Slave listbox not initialized.", "ERROR")
            return

        selected_indices = self.slave_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Error", "Please select one or more slave speakers to forget.")
            return

        ips_to_remove = [self.slave_listbox.get(i) for i in selected_indices]
        listing = "\n".join(f"  • {ip}" for ip in ips_to_remove)

        if messagebox.askyesno("Confirm",
                               f"Forget {len(ips_to_remove)} speaker(s) from the zone?\n\n"
                               f"{listing}\n\nThey stay hidden after restarting. "
                               "Use the 'Forgotten Speakers' tab to restore them."):
            for ip in ips_to_remove:
                self.forgotten_ips.add(ip)
                if ip in self.zone_slaves:
                    self.zone_slaves.remove(ip)

            self.zone_selection = []
            self.refresh_forgotten_tab()
            self.update_speaker_lists()
            self.save_settings()
            self.log(f"Forgot {len(ips_to_remove)} speaker(s) from zone (saved)", "SUCCESS")

    def on_slave_select(self, event=None):
        """Remember which rows are highlighted."""
        try:
            self.zone_selection = list(self.slave_listbox.curselection())
            self.save_settings()
        except tk.TclError:
            pass

    def on_master_select(self, event=None):
        self.master_ip = self.master_combo.get()
        self.save_settings()

    # -------------------------------------------------------------- discovery
    def _iface_ipv4(self):
        """Return [(ifname, ip, netmask), ...] for every up, non-loopback IPv4 interface."""
        out = []
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for _, name in socket.if_nameindex():
                try:
                    req = struct.pack("256s", name[:15].encode())
                    flags = struct.unpack(
                        "H", fcntl.ioctl(probe.fileno(), self.SIOCGIFFLAGS, req)[16:18])[0]
                    if not (flags & self.IFF_UP) or (flags & self.IFF_LOOPBACK):
                        continue
                    ip_addr = socket.inet_ntoa(
                        fcntl.ioctl(probe.fileno(), self.SIOCGIFADDR, req)[20:24])
                    mask = socket.inet_ntoa(
                        fcntl.ioctl(probe.fileno(), self.SIOCGIFNETMASK, req)[20:24])
                except OSError:
                    continue
                out.append((name, ip_addr, mask))
        finally:
            probe.close()
        return out

    def start_combined_scan(self):
        """Runs both SSDP and HTTP sweep discovery."""
        self.log("Starting combined discovery (SSDP + HTTP Sweep)...", "INFO")
        def run_all():
            self.discover_speakers()
            self.sweep_for_speakers()
        threading.Thread(target=run_all, daemon=True).start()

    def start_discovery(self):
        self.log("Starting SSDP scan on all interfaces...")
        threading.Thread(target=self.discover_speakers, daemon=True).start()

    def discover_speakers(self):
        """Multi-interface SSDP discovery - fixed for dual-homed hosts."""
        MSEARCH_TEMPLATE = ("M-SEARCH * HTTP/1.1\r\n"
                            "HOST: 239.255.255.250:1900\r\n"
                            'MAN: "ssdp:discover"\r\n'
                            "MX: 2\r\n"
                            "ST: {st}\r\n\r\n")
        TARGETS = ("ssdp:all",
                   "upnp:rootdevice",
                   "urn:schemas-upnp-org:device:MediaRenderer:1")
        GROUP = ("239.255.255.250", 1900)
        LISTEN_SECONDS = 6.0

        ifaces = self._iface_ipv4()
        if not ifaces:
            self.log("No usable IPv4 interface found.", "ERROR")
            self.root.after(0, self.update_speaker_lists)
            return

        own_ips = {ip for _, ip, _ in ifaces}
        socks = []
        for name, ip, _ in ifaces:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                             socket.inet_aton(ip))
                s.bind((ip, 0))          # pin the source address to this NIC
                s.setblocking(False)
                socks.append((name, s))
                self.log(f"M-SEARCH egress: {name} ({ip})")
            except OSError as e:
                self.log(f"Cannot use {name} ({ip}): {e}", "ERROR")

        if not socks:
            self.root.after(0, self.update_speaker_lists)
            return

        try:
            for attempt in range(3):
                for st in TARGETS:
                    packet = MSEARCH_TEMPLATE.format(st=st).encode()
                    for name, s in socks:
                        try:
                            s.sendto(packet, GROUP)
                        except OSError as e:
                            self.log(f"Send failed on {name}: {e}", "ERROR")
                if attempt < 2:
                    time.sleep(0.3)

            # Collect responses with select multiplexing
            deadline = time.time() + LISTEN_SECONDS
            found_any = False
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                readable, _, _ = select.select([s for _, s in socks], [], [],
                                               min(remaining, 0.5))
                for s in readable:
                    try:
                        data, addr = s.recvfrom(4096)
                    except OSError:
                        continue
                    ip = addr[0]
                    if ip in own_ips:
                        continue
                    if ip in self.forgotten_ips:
                        self.log(f"SKIPPED (forgotten): {ip}", "DEBUG")
                        continue
                    server = ""
                    m = re.search(r"(?im)^SERVER:\s*(.+)$",
                                  data.decode("utf-8", "ignore"))
                    if m:
                        server = m.group(1).strip()
                    if ip not in self.discovered_speakers:
                        self.log(f"Found speaker at {ip}"
                                 f"{' (' + server + ')' if server else ''}", "SUCCESS")
                        found_any = True
                    self.discovered_speakers[ip] = "Bose Speaker"

            if not found_any:
                self.log("SSDP scan finished. No new speakers found.", "INFO")
        except Exception as e:
            self.log(f"Discovery error: {e}", "ERROR")
        finally:
            for _, s in socks:
                s.close()
            self.root.after(0, self.update_speaker_lists)
            self.root.after(0, self.refresh_forgotten_tab)
            self.root.after(0, self.save_settings)

    def sweep_for_speakers(self):
        """TCP port-8090 sweep as fallback when multicast fails."""
        targets, own = set(), set()
        for _, ip, mask in self._iface_ipv4():
            own.add(ip)
            net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            if net.num_addresses > 512:
                net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
            targets.update(str(h) for h in net.hosts())
        targets -= own
        self.log(f"HTTP sweep of {len(targets)} addresses on port 8090...")

        found_count = 0

        def probe(addr):
            try:
                with socket.create_connection((addr, 8090), timeout=0.6):
                    pass
                res = requests.get(f"http://{addr}:8090/info", timeout=2)
                if res.status_code == 200 and "<info" in res.text:
                    root = ET.fromstring(res.text)
                    return addr, (root.findtext("name") or "Bose SoundTouch")
            except Exception:
                return None
            return None

        with ThreadPoolExecutor(max_workers=64) as pool:
            for hit in pool.map(probe, sorted(targets)):
                if not hit:
                    continue
                addr, name = hit
                if addr in self.forgotten_ips:
                    self.log(f"SKIPPED (forgotten): {addr}", "DEBUG")
                    continue
                if addr not in self.discovered_speakers:
                    self.log(f"Found {name} at {addr} (HTTP sweep)", "SUCCESS")
                    found_count += 1
                self.discovered_speakers[addr] = name

        if found_count == 0:
            self.log("HTTP sweep found no new speakers.", "INFO")
        else:
            self.log(f"Sweep completed: found {found_count} new speaker(s)", "SUCCESS")

        self.root.after(0, self.update_speaker_lists)
        self.root.after(0, self.refresh_forgotten_tab)
        self.root.after(0, self.save_settings)

    def start_http_sweep(self):
        """Public method to trigger HTTP fallback scan."""
        self.log("Starting HTTP port-8090 sweep...", "INFO")
        threading.Thread(target=self.sweep_for_speakers, daemon=True).start()

    def update_speaker_lists(self):
        """Rebuild every list from state, honouring the forgotten set."""
        visible = [ip for ip in self.discovered_speakers
                   if ip not in self.forgotten_ips]

        # --- active speaker combo --------------------------------------------
        self.speaker_combo['values'] = visible
        current = self.selected_speaker_ip.get()
        if current in visible:
            self.speaker_combo.set(current)
        elif visible:
            self.speaker_combo.current(0)
            self.selected_speaker_ip.set(visible[0])
        else:
            self.selected_speaker_ip.set("")
            self.speaker_combo.set("")

        # --- master combo -----------------------------------------------------
        if hasattr(self, 'master_combo'):
            self.master_combo['values'] = visible
            if self.master_ip in visible:
                self.master_combo.set(self.master_ip)
            elif visible:
                self.master_combo.current(0)
                self.master_ip = visible[0]
            else:
                self.master_combo.set("")
                self.master_ip = ""

        # --- zone slave listbox ----------------------------------------------
        if hasattr(self, 'slave_listbox'):
            # Drop anything no longer visible, then append newcomers
            self.zone_slaves = [ip for ip in self.zone_slaves if ip in visible]
            for ip in visible:
                if ip not in self.zone_slaves:
                    self.zone_slaves.append(ip)

            self.slave_listbox.delete(0, tk.END)
            for ip in self.zone_slaves:
                self.slave_listbox.insert(tk.END, ip)

            # Reapply the remembered highlight where still valid
            self.slave_listbox.selection_clear(0, tk.END)
            size = self.slave_listbox.size()
            kept = []
            for idx in self.zone_selection:
                if 0 <= idx < size:
                    self.slave_listbox.selection_set(idx)
                    kept.append(idx)
            self.zone_selection = kept

    # ----------------------------------------------------------------- forgotten
    def build_forgotten_tab(self):
        """Tab to manage forgotten speakers and permanently remove records."""
        frame = ttk.Frame(self.tab_forgotten, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Manage Saved Speakers",
                  font=("Arial", 12, "bold")).pack(pady=10)

        ttk.Label(frame,
                  text="Everything the app remembers lives here.\n"
                       "'Restore' brings a forgotten IP back to the visible lists.\n"
                       "'Remove' erases the record permanently - it stays gone "
                       "across restarts.",
                  wraplength=450, justify=tk.LEFT).pack(pady=5)

        # Listbox combining forgotten and known speakers
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        self.forgotten_listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, height=10)
        self.forgotten_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listboxes.append(self.forgotten_listbox)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.forgotten_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.forgotten_listbox.config(yscrollcommand=scrollbar.set)

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=10)

        ttk.Button(btn_frame, text="↩️ Restore Selected",
                   command=self.restore_forgotten).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="♻️ Restore All",
                   command=self.restore_all_forgotten).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="❌ Remove Selected Permanently",
                   command=self.remove_selected_permanently).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💣 Delete ALL Records",
                   command=self.purge_all_records).pack(side=tk.LEFT, padx=5)

        # Stats
        self.forgotten_stats = ttk.Label(frame, text="", font=("Arial", 9))
        self.forgotten_stats.pack(pady=10)

        self.refresh_forgotten_tab()

    def refresh_forgotten_tab(self):
        """Update the saved-speakers listbox and stats line."""
        if not hasattr(self, 'forgotten_listbox'):
            return

        self.forgotten_listbox.delete(0, tk.END)
        # Show forgotten ones first (marked), then visible ones
        for ip in sorted(self.forgotten_ips):
            label = self.discovered_speakers.get(ip, "Unknown")
            self.forgotten_listbox.insert(tk.END, f"{ip} (forgotten - {label})")
        for ip in sorted(self.discovered_speakers.keys()):
            if ip not in self.forgotten_ips:
                self.forgotten_listbox.insert(tk.END, f"{ip} ({self.discovered_speakers[ip]})")

        self.forgotten_stats.config(
            text=f"Total saved: {len(self.discovered_speakers)} | "
                 f"Forgotten: {len(self.forgotten_ips)} | "
                 f"Visible: {len(self.discovered_speakers) - len(self.forgotten_ips)}"
        )

    def restore_forgotten(self):
        """Restore selected forgotten speakers."""
        selected_indices = self.forgotten_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Error", "Please select speaker(s) to restore.")
            return

        restored = 0
        for idx in selected_indices:
            # Extract IP from the displayed text "IP (...)"
            text = self.forgotten_listbox.get(idx)
            ip = text.split('(')[0].strip()
            if ip in self.forgotten_ips:
                self.forgotten_ips.discard(ip)
                restored += 1

        self.log(f"Restored {restored} speaker(s)", "SUCCESS")
        self.refresh_forgotten_tab()
        self.update_speaker_lists()
        self.save_settings()

    def restore_all_forgotten(self):
        """Restore all forgotten speakers."""
        if not self.forgotten_ips:
            messagebox.showinfo("Info", "No forgotten speakers to restore.")
            return

        count = len(self.forgotten_ips)
        if messagebox.askyesno("Confirm",
                               f"Restore ALL {count} forgotten speakers?"):
            self.forgotten_ips.clear()
            self.log(f"Restored all {count} forgotten speakers", "SUCCESS")
            self.refresh_forgotten_tab()
            self.update_speaker_lists()
            self.save_settings()
            self.tabControl.select(self.tab_control)

    # ------------------------------------------------------------ factory reset
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

    # ------------------------------------------------------------------ zoning
    def build_pairing_tab(self):
        frame = ttk.Frame(self.tab_pairing, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Create Synchronized Zone",
                  font=("Arial", 12, "bold")).pack(pady=10)

        zone_f = ttk.Frame(frame)
        zone_f.pack(pady=10)

        ttk.Label(zone_f, text="1. Select Master Speaker:").grid(row=0, column=0,
                                                                 sticky=tk.W, pady=5)
        self.master_combo = ttk.Combobox(zone_f, state="readonly")
        self.master_combo.grid(row=0, column=1, padx=10, pady=5)
        self.master_combo.bind("<<ComboboxSelected>>", self.on_master_select)

        ttk.Label(zone_f, text="2. Select Slave Speakers:").grid(row=1, column=0,
                                                                 sticky=tk.W, pady=5)
        self.slave_listbox = tk.Listbox(zone_f, selectmode=tk.MULTIPLE, height=6)
        self.slave_listbox.grid(row=1, column=1, padx=10, pady=5)
        self.slave_listbox.bind("<<ListboxSelect>>", self.on_slave_select)
        self.listboxes.append(self.slave_listbox)

        btn_f = ttk.Frame(frame)
        btn_f.pack(pady=20)
        ttk.Button(btn_f, text="🚀 Sync All Selected",
                   command=self.start_sync_thread).pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_f, text="🔍 Verify Zone",
                   command=self.verify_zone).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_f, text="❌ Clear Zone",
                   command=self.clear_zone).pack(side=tk.LEFT, padx=5)

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

        # STRATEGY 1: The "Gabbo" Standard (most likely to bypass 1019)
        self.log("Trial 1: Testing 'Gabbo' sender attribute...")
        slave_xml = "".join([f'<member ipaddress="{s}">{self.get_device_id(s)}</member>'
                             for s in final_slaves])
        payload1 = f'<zone master="{master_id}" sender="Gabbo">{slave_xml}</zone>'
        if self._attempt_sync(master_ip, payload1):
            return

        # STRATEGY 2: The "Binary-Gabbo" Hybrid (PCAP header + Gabbo)
        self.log("Trial 2: Testing Binary Header + Gabbo...")
        binary_header = bytes([0x00, 0x00, 0x00, 0x08, 0x01, 0x00,
                               0x00, 0x06, 0x00, 0x00, 0x00])
        payload2 = binary_header + payload1.encode('utf-8')
        if self._attempt_sync(master_ip, payload2):
            return

        # STRATEGY 3: The "Member" Format (from the OpenAPI spec)
        self.log("Trial 3: Testing Member Format...")
        payload3 = f'<zone master="{master_id}">{slave_xml}</zone>'
        if self._attempt_sync(master_ip, payload3):
            return

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
                found_slaves = [s.attrib.get('ip') or s.text
                                for s in (root.findall(".//member") or root.findall(".//slave"))]
                if found_slaves:
                    self.log("SUCCESS: Sync verified!", "SUCCESS")
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Success", "Zone verified and active!"))
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
                        self.root.after(0, lambda: messagebox.showinfo(
                            "Zone Status", "No slaves found in this zone."))
                    else:
                        self.log(f"Master reports {len(slave_list)} slaves: "
                                 f"{', '.join(slave_list)}", "SUCCESS")
                        self.root.after(0, lambda: messagebox.showinfo(
                            "Zone Status",
                            f"Current Zone Members:\n\nMaster: {master}\n"
                            f"Slaves: {', '.join(slave_list)}"))
                else:
                    self.log(f"Verify failed. Status: {res.status_code}", "ERROR")
            except Exception as e:
                self.log(f"Verification error: {e}", "ERROR")

        threading.Thread(target=run_verify, daemon=True).start()

    def clear_zone(self):
        master = self.master_combo.get()
        if not master:
            return
        payload = '<zone masterid=""></zone>'
        try:
            res = requests.post(f"http://{master}:8090/setZone", data=payload,
                                headers={'Content-Type': 'text/xml'}, timeout=5)
            if res.status_code == 200:
                self.log("Zone cleared successfully.", "SUCCESS")
                messagebox.showinfo("Success", "Zone cleared.")
        except Exception as e:
            self.log(f"Clear failed: {e}", "ERROR")

    # ------------------------------------------------------------- danger zone
    def build_danger_tab(self):
        frame = ttk.Frame(self.tab_danger, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        warning_f = ttk.Frame(frame)
        warning_f.pack(pady=20)

        self.danger_label = ttk.Label(warning_f, text="WARNING: FACTORY RESET",
                                      font=("Arial", 14, "bold"))
        self.danger_label.pack(pady=10)

        ttk.Label(warning_f,
                  text="This will wipe all Wi-Fi settings, presets, and paired devices.\n"
                       "The speaker will reboot into Setup Mode.",
                  wraplength=400, justify=tk.CENTER).pack(pady=10)

        self.add_reset_links(warning_f, target_tab=self.tab_setup)
        ttk.Button(frame, text="⚠️ FACTORY RESET SELECTED SPEAKER",
                   command=self.factory_reset).pack(pady=20)


if __name__ == "__main__":
    root = tk.Tk()
    app = BoseQuadManager(root)
    root.mainloop()