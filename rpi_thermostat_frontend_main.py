import customtkinter as ctk
from CTkMessagebox import CTkMessagebox
import requests
import threading
import time

# Cambia con l'IP reale del Raspberry Pi
RASPBERRY_IP = "192.168.68.128"
API_STATUS = f"http://{RASPBERRY_IP}:5000/status"
API_SETTINGS = f"http://{RASPBERRY_IP}:5000/settings"
API_MANUAL = f"http://{RASPBERRY_IP}:5000/manual"
API_SHUTDOWN = f"http://{RASPBERRY_IP}:5000/shutdown"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_FONT = "Bahnschrift"
GLOBAL_FONT = (APP_FONT, 14)

# --- Numeric keypad ---
_open_keypad_refs = {}

def open_numeric_pad(parent, entry_widget, allow_decimal=True, title="Numeric keypad", keep_previous=False):
    key = id(entry_widget)
    existing = _open_keypad_refs.get(key)
    if existing:
        try:
            existing.lift()
            return
        except Exception:
            pass

    pad = ctk.CTkToplevel(parent)
    pad.title(title)
    pad.geometry("480x480")
    pad.attributes("-topmost", True)
    _open_keypad_refs[key] = pad
    pad.transient(parent)

    start_value = entry_widget.get() if keep_previous else ""
    display_var = ctk.StringVar(value=start_value)
    display = ctk.CTkEntry(pad, textvariable=display_var, font=(APP_FONT, 28), justify="right")
    display.pack(fill="x", padx=12, pady=(12, 6))

    def add_char(ch):
        cur = display_var.get()
        if ch == "." and (not allow_decimal or "." in cur):
            return
        display_var.set(cur + ch)

    def backspace():
        display_var.set(display_var.get()[:-1])

    def clear_all():
        display_var.set("")

    def do_ok():
        val = display_var.get()
        entry_widget.delete(0, "end")
        entry_widget.insert(0, val)
        on_close()

    def do_cancel():
        on_close()

    btn_frame = ctk.CTkFrame(pad)
    btn_frame.pack(expand=True, fill="both", padx=10, pady=(6, 4))
    buttons = [
        ("7", lambda: add_char("7")), ("8", lambda: add_char("8")), ("9", lambda: add_char("9")),
        ("4", lambda: add_char("4")), ("5", lambda: add_char("5")), ("6", lambda: add_char("6")),
        ("1", lambda: add_char("1")), ("2", lambda: add_char("2")), ("3", lambda: add_char("3")),
        (".", lambda: add_char(".")), ("0", lambda: add_char("0")), ("←", backspace),
    ]
    rows = 4
    cols = 3
    for idx, (txt, cmd) in enumerate(buttons):
        r = idx // cols
        c = idx % cols
        b = ctk.CTkButton(btn_frame, text=txt, command=cmd, font=(APP_FONT, 20), height=40)
        b.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
        btn_frame.grid_columnconfigure(c, weight=1)
        btn_frame.grid_rowconfigure(r, weight=1)

    bottom = ctk.CTkFrame(pad)
    bottom.pack(fill="x", padx=12, pady=(4, 12))
    ctk.CTkButton(bottom, text="Clear", command=clear_all, font=(APP_FONT, 20), height=40).pack(side="left", expand=True, fill="x", padx=6, pady=6)
    ctk.CTkButton(bottom, text="Cancel", command=do_cancel, font=(APP_FONT, 20), height=40).pack(side="left", expand=True, fill="x", padx=6, pady=6)
    ctk.CTkButton(bottom, text="OK", command=do_ok, font=(APP_FONT, 20), height=40).pack(side="left", expand=True, fill="x", padx=6, pady=6)

    def on_close(event=None):
        try:
            _open_keypad_refs.pop(key, None)
            pad.destroy()
        except Exception:
            pass

    pad.protocol("WM_DELETE_WINDOW", on_close)
    pad.bind("<Destroy>", lambda e: _open_keypad_refs.pop(key, None))
    pad.grab_set()
    pad.focus_force()

# --- Canale Frame (riutilizzabile per CH1 e CH2) ---
class ChannelFrame(ctk.CTkFrame):
    def __init__(self, parent, ch_num, title=None, header_fg="#2a2a2a", header_text_color="#e5e5e5"):
        super().__init__(
            parent,
            fg_color="transparent",
            corner_radius=10,
            border_width=2,
            border_color="#4a4a4a"
        )
        self.ch_num = ch_num
        label_font = (APP_FONT, 16)

        # --- Header (barra titolo) ---
        header_text = title if title is not None else f"CH{ch_num}"
        self.header = ctk.CTkFrame(self, fg_color=header_fg, corner_radius=10)
        self.header.pack(fill="x", padx=0, pady=(0, 6))

        self.header_label = ctk.CTkLabel(
            self.header,
            text=header_text,
            font=(APP_FONT, 18, "bold"),
            text_color=header_text_color
        )
        self.header_label.pack(side="left", padx=12, pady=6)

        # --- Corpo ---
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Colonne
        self.left_col = ctk.CTkFrame(self.body, fg_color="transparent")
        self.left_col.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        self.right_col = ctk.CTkFrame(self.body, fg_color="transparent")
        self.right_col.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # --- Colonna sinistra: parametri ---
        self.sp_label = ctk.CTkLabel(self.left_col, text=f"Setpoint CH{ch_num} (°C):", font=GLOBAL_FONT)
        self.sp_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.sp_entry = ctk.CTkEntry(self.left_col, font=GLOBAL_FONT)
        self.sp_entry.grid(row=0, column=1, padx=5, pady=5)

        ctk.CTkButton(
            self.left_col,
            text="Conferma",
            command=lambda: self.update_settings("setpoint"),
            font=GLOBAL_FONT
        ).grid(row=0, column=2, padx=5, pady=5)

        self.hyst_label = ctk.CTkLabel(self.left_col, text="Isteresi (°C):", font=GLOBAL_FONT)
        self.hyst_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)

        self.hyst_entry = ctk.CTkEntry(self.left_col, font=GLOBAL_FONT)
        self.hyst_entry.grid(row=1, column=1, padx=5, pady=5)

        ctk.CTkButton(
            self.left_col,
            text="Conferma",
            command=lambda: self.update_settings("hysteresis"),
            font=GLOBAL_FONT
        ).grid(row=1, column=2, padx=5, pady=5)

        self.mode_var = ctk.StringVar(value="1 - HEATING")
        self.mode_label = ctk.CTkLabel(self.left_col, text="Modalità:", font=GLOBAL_FONT)
        self.mode_label.grid(row=2, column=0, sticky="w", padx=5, pady=5)

        self.mode_menu = ctk.CTkOptionMenu(
            self.left_col,
            values=["1 - HEATING", "2 - COOLING"],
            variable=self.mode_var,
            font=GLOBAL_FONT
        )
        self.mode_menu.grid(row=2, column=1, padx=5, pady=5)

        ctk.CTkButton(
            self.left_col,
            text="Conferma",
            command=lambda: self.update_settings("mode"),
            font=GLOBAL_FONT
        ).grid(row=2, column=2, padx=5, pady=5)

        # --- Checkbox forzatura manuale ---
        self.manual_enable_var = ctk.IntVar(value=0)
        self.manual_cb = ctk.CTkCheckBox(
            self.left_col,
            text="Attiva forzatura",
            variable=self.manual_enable_var,
            command=self.manual_enable_toggle,
            font=GLOBAL_FONT
        )
        self.manual_cb.grid(row=3, column=0, columnspan=3, sticky="w", padx=5, pady=(10, 5))

        # --- Pulsanti manuali ON/OFF ---
        btns_frame = ctk.CTkFrame(self.left_col, fg_color="transparent")
        btns_frame.grid(row=4, column=0, columnspan=3, sticky="w", padx=5, pady=(5, 5))

        self.on_btn = ctk.CTkButton(
            btns_frame,
            text="ON",
            width=80,
            command=lambda: self.manual_set(True),
            font=GLOBAL_FONT
        )
        self.on_btn.pack(side="left", padx=(0, 8))

        self.off_btn = ctk.CTkButton(
            btns_frame,
            text="OFF",
            width=80,
            command=lambda: self.manual_set(False),
            font=GLOBAL_FONT
        )
        self.off_btn.pack(side="left")

        # Disabilitati finché non si attiva la forzatura
        self.update_manual_buttons_state()

        # --- Colonna destra: stato ---
        self.temp_label = ctk.CTkLabel(self.right_col, text="Temperatura: -- °C", font=label_font)
        self.temp_label.pack(pady=5)

        self.sp_curr_label = ctk.CTkLabel(self.right_col, text="Setpoint attuale: --", font=label_font)
        self.sp_curr_label.pack(pady=5)

        self.hyst_curr_label = ctk.CTkLabel(self.right_col, text="Isteresi attuale: --", font=label_font)
        self.hyst_curr_label.pack(pady=5)

        self.mode_curr_label = ctk.CTkLabel(self.right_col, text="Modalità: --", font=label_font)
        self.mode_curr_label.pack(pady=5)

        self.relay_label = ctk.CTkLabel(self.right_col, text="Relay: --", font=label_font)
        self.relay_label.pack(pady=5)

        # Keypad bind
        self.sp_entry.bind("<Button-1>", lambda e: open_numeric_pad(self, self.sp_entry))
        self.hyst_entry.bind("<Button-1>", lambda e: open_numeric_pad(self, self.hyst_entry))

    # --- SETTINGS API ---
    def update_settings(self, param=None):
        try:
            payload = {}
            prefix = f"CH{self.ch_num}_"

            if param == "setpoint" or param is None:
                payload[prefix + "setpoint"] = float(self.sp_entry.get())

            if param == "hysteresis" or param is None:
                payload[prefix + "hysteresis"] = float(self.hyst_entry.get())

            if param == "mode" or param is None:
                mode_num = float(self.mode_var.get().split(" ")[0])
                payload[prefix + "mode"] = mode_num

            if payload:
                requests.post(API_SETTINGS, json=payload, timeout=2)
        except Exception as e:
            print(f"Errore update CH{self.ch_num}: {e}")

    # --- TOGGLE FORZATURA ---
    def manual_enable_toggle(self):
        try:
            val = 1.0 if self.manual_enable_var.get() else 0.0
            requests.post(
                API_SETTINGS,
                json={f"CH{self.ch_num}_manual_enable": val},
                timeout=2
            )
        except Exception as e:
            print(f"Errore manual enable CH{self.ch_num}: {e}")

        self.update_manual_buttons_state()

    def update_manual_buttons_state(self):
        enabled = bool(self.manual_enable_var.get())
        state = "normal" if enabled else "disabled"
        self.on_btn.configure(state=state)
        self.off_btn.configure(state=state)

    # --- COMANDO MANUALE ON/OFF ---
    def manual_set(self, state: bool):
        try:
            requests.post(
                API_MANUAL,
                json={f"CH{self.ch_num}_on": state},
                timeout=2
            )
        except Exception as e:
            print(f"Errore manual CH{self.ch_num}: {e}")

# --- Main App ---
class ThermostatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Termostato")
        self.geometry("1400x500")
        self.iconbitmap("rpi_thermostat.ico")
        self.update_msg = ctk.CTkLabel(self, text="", font=GLOBAL_FONT, text_color="green")
        self.update_msg.pack(pady=5)

        # Stato di connessione alla RPI
        self.connected = False
        self.connection_label = ctk.CTkLabel(
            self,
            text="DISCONNECTED",
            font=(APP_FONT, 14, "bold"),
            text_color="red"
        )
        self.connection_label.pack(pady=5)

        # Contenitore canali
        self.channels_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.channels_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Canali
        self.ch1 = ChannelFrame(self.channels_frame, 1, title="CHANNEL 1")
        self.ch1.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        self.ch2 = ChannelFrame(self.channels_frame, 2, title="CHANNEL 2")
        self.ch2.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        '''
        # Pulsanti manuali ON/OFF centrali
        manual_frame = ctk.CTkFrame(self, fg_color="transparent")
        manual_frame.pack(fill="x", padx=20, pady=10)
        self.on_btn = ctk.CTkButton(manual_frame, text="ON", command=lambda: self.manual(True), font=GLOBAL_FONT)
        self.on_btn.pack(side="left", padx=10)
        self.off_btn = ctk.CTkButton(manual_frame, text="OFF", command=lambda: self.manual(False), font=GLOBAL_FONT)
        self.off_btn.pack(side="left", padx=10)
        '''

        # Pulsante spegni
        self.shutdown_btn = ctk.CTkButton(self, text="Spegni RPi", command=self.shutdown_rpi, font=GLOBAL_FONT)
        self.shutdown_btn.pack(side="bottom", pady=10)

        # Start loop aggiornamento stato
        threading.Thread(target=self.update_loop, daemon=True).start()

    def set_connection_state(self, state: bool):
        if state == self.connected:
            return  # evita aggiornamenti inutili

        self.connected = state

        if state:
            self.connection_label.configure(text="CONNECTED", text_color="green")
        else:
            self.connection_label.configure(text="DISCONNECTED", text_color="red")

            # opzionale: reset valori UI
            for ch in [self.ch1, self.ch2]:
                ch.temp_label.configure(text="Temperatura: -- °C")
                ch.sp_curr_label.configure(text="Setpoint attuale: --")
                ch.hyst_curr_label.configure(text="Isteresi attuale: --")
                ch.mode_curr_label.configure(text="Modalità: --")
                ch.relay_label.configure(text="Relay: --")

    def update_loop(self):
        while True:
            try:
                r = requests.get(API_STATUS, timeout=2)
                r.raise_for_status()
                data = r.json()

                self.set_connection_state(True)

                # CH1
                ch1_data = data.get("CH1", {})
                self.ch1.temp_label.configure(text=f"Temperatura: {ch1_data.get('temperature', '--')} °C")
                self.ch1.sp_curr_label.configure(text=f"Setpoint attuale: {ch1_data.get('setpoint', '--')}")
                self.ch1.hyst_curr_label.configure(text=f"Isteresi attuale: {ch1_data.get('hysteresis', '--')}")
                mode_label = "HEATING" if ch1_data.get("mode") == 1 else "COOLING"
                self.ch1.mode_curr_label.configure(text=f"Modalità: {mode_label}")
                relay_state = "ON" if ch1_data.get("relay", False) else "OFF"
                self.ch1.relay_label.configure(text=f"Relay: {relay_state}")

                # CH2
                ch2_data = data.get("CH2", {})
                self.ch2.temp_label.configure(text=f"Temperatura: {ch2_data.get('temperature', '--')} °C")
                self.ch2.sp_curr_label.configure(text=f"Setpoint attuale: {ch2_data.get('setpoint', '--')}")
                self.ch2.hyst_curr_label.configure(text=f"Isteresi attuale: {ch2_data.get('hysteresis', '--')}")
                mode_label2 = "HEATING" if ch2_data.get("mode") == 1 else "COOLING"
                self.ch2.mode_curr_label.configure(text=f"Modalità: {mode_label2}")
                relay_state2 = "ON" if ch2_data.get("relay", False) else "OFF"
                self.ch2.relay_label.configure(text=f"Relay: {relay_state2}")

            except Exception:
                self.set_connection_state(False)

            time.sleep(1)

    def manual(self, state: bool):
        try:
            requests.post(API_MANUAL, json={"CH1_on": state, "CH2_on": state}, timeout=2)
        except:
            pass

    def shutdown_rpi(self):
        try:
            msg = CTkMessagebox(title="Conferma", message="Spegni RPi?", icon="warning", option_1="No", option_2="Sì")
            if msg.get() == "Sì":
                requests.post(API_SHUTDOWN, timeout=2)
        except:
            pass

def main():
    app = ThermostatApp()
    app.mainloop()

if __name__ == "__main__":
    main()