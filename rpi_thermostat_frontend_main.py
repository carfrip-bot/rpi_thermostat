import customtkinter as ctk
from CTkMessagebox import CTkMessagebox
import requests
import threading
import time
from datetime import datetime
from tkcalendar import Calendar
import logging

# Cambia con l'IP reale del Raspberry Pi
RASPBERRY_IP = "192.168.68.128" # "192.168.1.31"
API_STATUS = f"http://{RASPBERRY_IP}:5000/status"
API_SETTINGS = f"http://{RASPBERRY_IP}:5000/settings"
API_MANUAL = f"http://{RASPBERRY_IP}:5000/manual"
API_SHUTDOWN = f"http://{RASPBERRY_IP}:5000/shutdown"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_FONT = "Bahnschrift"
CALENDAR_FONT = "Bahnschrift 24"
GLOBAL_FONT = (APP_FONT, 14)

# Configurazione Logger
logging.basicConfig(
    filename='log.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logging.info("=== Applicazione Termostato Avviata ===")

# --- Numeric keypad ---
_open_keypad_refs = {}

def open_numeric_pad(parent, entry_widget, allow_decimal=True, title="Numeric keypad", keep_previous=False, on_ok=None):
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
        if callable(on_ok):
            on_ok()
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
    ctk.CTkButton(bottom, text="OK", command=do_ok, font=(APP_FONT, 20), height=40).pack(side="left", expand=True,
                                                                                         fill="x", padx=6, pady=6)
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

def center_window(win):
    win.update_idletasks()
    width = win.winfo_width()
    height = win.winfo_height()
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height * 2)
    win.geometry(f"+{x}+{y}")

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

        self.plan_btn = ctk.CTkButton(
            self.left_col,
            text="PLAN",
            command=self.open_plan_popup,
            font=GLOBAL_FONT
        )
        self.plan_btn.grid(row=4, column=2, columnspan=3, pady=10)

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
                logging.info(f"Invio parametri: {payload}")
        except Exception as e:
            print(f"Errore update CH{self.ch_num}: {e}")

    # --- TOGGLE FORZATURA ---
    def manual_enable_toggle(self):
        try:
            val = bool(self.manual_enable_var.get())
            # Chiama l'endpoint corretto per attivare la modalità manuale globale
            requests.post(
                API_MANUAL,
                json={"manual": val},
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
            # Costruisce l'URL specifico per il canale (es. /manual/ch1)
            ch_id = f"ch{self.ch_num}"
            requests.post(
                f"{API_MANUAL}/{ch_id}",
                json={"state": state},
                timeout=2
            )
        except Exception as e:
            print(f"Errore manual CH{self.ch_num}: {e}")

    def open_plan_popup(self):
        channel = self.ch_num
        popup = ctk.CTkToplevel(self)
        popup.title(f"Pianificazione CH{channel}")
        popup.geometry("600x650")
        center_window(popup)
        popup.lift()
        popup.focus_force()
        popup.grab_set()
        popup.attributes("-topmost", True)
        popup.after(200, lambda: popup.attributes("-topmost", False))

        plan_data = []

        title_label = ctk.CTkLabel(popup, text=f"Pianificazione CH{channel}", font=("Arial", 18, "bold"))
        title_label.pack(pady=10)

        count_var = ctk.StringVar(value="2")

        def open_count_pad(event=None):
            open_numeric_pad(
                parent=popup,
                entry_widget=count_entry,
                allow_decimal=False,
                title="Numero di intervalli",
                keep_previous=False,
                on_ok=rebuild_intervals
            )

        count_label = ctk.CTkLabel(popup, text="Numero di intervalli:")
        count_label.pack()
        count_entry = ctk.CTkEntry(popup, textvariable=count_var, justify="center")
        count_entry.pack(pady=5)
        count_entry.bind("<Button-1>", open_count_pad)

        container = ctk.CTkFrame(popup)
        container.pack(fill="both", expand=True, padx=10, pady=10)
        container.grid_columnconfigure(0, weight=1)

        entries = []

        # -------- Placeholder helper --------
        def add_placeholder(entry, placeholder_text):
            entry.insert(0, placeholder_text)
            entry.configure(text_color="#888")

            def on_focus_in(event):
                if entry.get() == placeholder_text:
                    entry.delete(0, "end")
                    entry.configure(text_color="#fff")

            def on_focus_out(event):
                if entry.get() == "":
                    entry.insert(0, placeholder_text)
                    entry.configure(text_color="#888")

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)

        # -------- Validation helpers --------
        def mark_row_invalid(index):
            row_frame = container.winfo_children()[index]
            for widget in row_frame.winfo_children():
                if isinstance(widget, ctk.CTkEntry):
                    widget.configure(border_color="red")

        def reset_all_borders():
            default_border = ctk.ThemeManager.theme["CTkEntry"]["border_color"]
            for row in container.winfo_children():
                for widget in row.winfo_children():
                    if isinstance(widget, ctk.CTkEntry):
                        widget.configure(border_color=default_border)

        def validate_plan():
            valid = True
            reset_all_borders()

            parsed_rows = []

            for i, (start_var, end_var, _) in enumerate(entries):
                try:
                    start_dt = datetime.strptime(start_var.get(), "%d/%m/%Y")
                    end_dt = datetime.strptime(end_var.get(), "%d/%m/%Y")
                    parsed_rows.append((start_dt, end_dt))
                except:
                    valid = False
                    continue

            for i in range(len(parsed_rows)):
                start_dt, end_dt = parsed_rows[i]

                if end_dt < start_dt:
                    valid = False
                    mark_row_invalid(i)

                if i < len(parsed_rows) - 1:
                    next_start, _ = parsed_rows[i + 1]
                    if end_dt >= next_start:
                        valid = False
                        mark_row_invalid(i)
                        mark_row_invalid(i + 1)

            confirm_button.configure(state="normal" if valid else "disabled")

        def _on_var_change(name: str, index: str, mode: str) -> None:
            validate_plan()

        # -------- Rebuild intervals --------
        def rebuild_intervals():
            for widget in container.winfo_children():
                widget.destroy()
            entries.clear()

            try:
                count = int(count_var.get())
            except:
                return

            for i in range(count):
                row = ctk.CTkFrame(container)
                row.pack(fill="x", pady=5)

                row.grid_columnconfigure(1, weight=1)
                row.grid_columnconfigure(2, weight=1)
                row.grid_columnconfigure(3, weight=1)

                interval_label = ctk.CTkLabel(row, text=f"Intervallo {i + 1}")
                interval_label.grid(row=0, column=0, padx=5)

                start_var = ctk.StringVar()
                end_var = ctk.StringVar()
                setpoint_var = ctk.StringVar()

                def open_calendar(d_var):
                    cal_popup = ctk.CTkToplevel(popup)
                    cal_popup.title("Seleziona una data")
                    cal_popup.geometry("550x600")
                    center_window(cal_popup)
                    cal_popup.minsize(550, 600)
                    cal_popup.transient(popup)
                    cal_popup.grab_set()

                    cal = Calendar(cal_popup, date_pattern="dd/mm/yyyy", font=CALENDAR_FONT, locale='it_IT')
                    cal.pack(pady=10, expand=True, fill="both")

                    def confirm_date():
                        d_var.set(cal.get_date())
                        cal_popup.destroy()

                    confirm_btn = ctk.CTkButton(cal_popup, text="OK", command=confirm_date)
                    confirm_btn.pack(pady=10)

                start_entry = ctk.CTkEntry(row, textvariable=start_var)
                start_entry.grid(row=0, column=1, padx=5, sticky="ew")
                add_placeholder(start_entry, "Data iniziale")
                start_entry.bind("<Button-1>", lambda e, dv=start_var: open_calendar(dv))

                end_entry = ctk.CTkEntry(row, textvariable=end_var)
                end_entry.grid(row=0, column=2, padx=5, sticky="ew")
                add_placeholder(end_entry, "Data finale")
                end_entry.bind("<Button-1>", lambda e, dv=end_var: open_calendar(dv))

                start_var.trace_add("write", _on_var_change)
                end_var.trace_add("write", _on_var_change)

                setpoint_entry = ctk.CTkEntry(row, textvariable=setpoint_var)
                setpoint_entry.grid(row=0, column=3, padx=5, sticky="ew")
                add_placeholder(setpoint_entry, "Temperatura (°C)")
                setpoint_entry.bind(
                    "<Button-1>",
                    lambda e, sp_entry=setpoint_entry: open_numeric_pad(
                        parent=popup,
                        entry_widget=sp_entry,
                        allow_decimal=True,
                        title="Setpoint °C",
                        keep_previous=False
                    )
                )

                entries.append((start_var, end_var, setpoint_var))

        rebuild_intervals()

        # -------- Confirm --------
        def confirm_plan():
            plan_data = []

            for start_var, end_var, sp_var in entries:
                start_str = start_var.get()
                end_str = end_var.get()
                sp_str = sp_var.get()

                if not start_str or not end_str or not sp_str:
                    continue

                try:
                    # Inizio giornata: ore 00:00:00
                    start_dt = datetime.strptime(start_str, "%d/%m/%Y").replace(
                        hour=0, minute=0, second=0
                    )
                    # Fine giornata: ore 23:59:59
                    end_dt = datetime.strptime(end_str, "%d/%m/%Y").replace(
                        hour=23, minute=59, second=59
                    )
                    setpoint = float(sp_str)

                    if start_dt <= end_dt:
                        # Il backend si aspetta una lista di [start_iso, end_iso, setpoint]
                        plan_data.append([start_dt.isoformat(), end_dt.isoformat(), setpoint])
                except Exception as e:
                    print(f"Errore parsing plan: {e}")
                    continue

            # Invia i dati al backend (anche se è vuoto, così resetta il plan se togli tutti gli intervalli)
            try:
                ch_id = f"ch{channel}"
                url = f"http://{RASPBERRY_IP}:5000/schedule/{ch_id}"
                requests.post(url, json={"schedule": plan_data}, timeout=2)
                # Log scheduling
                logging.info(f"Inviato nuovo SCHEDULING per Canale {channel}: {plan_data}")
            except Exception as e:
                logging.info(f"Errore nell'incio dello SCHEDULING per Canale {channel}: {e}")
                print(f"Errore invio schedule: {e}")

            popup.destroy()

        confirm_button = ctk.CTkButton(
            popup,
            text="Conferma Pianificazione",
            command=confirm_plan,
            state="disabled"
        )
        confirm_button.pack(pady=20)

    '''
    def open_calendar(self, target_entry):
        cal_win = ctk.CTkToplevel(self)
        cal_win.title("Seleziona una data")
        cal_win.geometry("550x600")
        center_window(cal_win)
        cal_win.minsize(550, 600)
        cal_win.grab_set()

        cal = Calendar(cal_win, selectmode="day", date_pattern="dd/mm/yyyy")
        cal.pack(fill="both", expand=True, padx=10, pady=10)

        def confirm():
            target_entry.delete(0, "end")
            target_entry.insert(0, cal.get_date())
            cal_win.destroy()

        ctk.CTkButton(cal_win, text="OK", command=confirm).pack(pady=5)
    '''

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
            text="TERMOSTATO OFFLINE",
            font=(APP_FONT, 25, "bold"),
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

        # Pulsante spegni
        self.shutdown_btn = ctk.CTkButton(self, text="Spegni Termostato", command=self.shutdown_rpi, font=GLOBAL_FONT)
        self.shutdown_btn.pack(side="bottom", pady=10)

        # Start loop aggiornamento stato
        threading.Thread(target=self.update_loop, daemon=True).start()

    def set_connection_state(self, state: bool):
        if state == self.connected:
            return  # evita aggiornamenti inutili

        self.connected = state

        if state:
            self.connection_label.configure(text="TERMOSTATO ONLINE", text_color="green")
        else:
            self.connection_label.configure(text="TERMOSTATO OFFLINE", text_color="red")

            # UI Parameters Reset
            for ch in [self.ch1, self.ch2]:
                ch.temp_label.configure(text="Temperatura: -- °C")
                ch.sp_curr_label.configure(text="Setpoint attuale: --")
                ch.hyst_curr_label.configure(text="Isteresi attuale: --")
                ch.mode_curr_label.configure(text="Modalità: --")
                ch.relay_label.configure(text="Relay: --")

    def update_loop(self):
        was_connected = True  # Variabile d'appoggio per log
        last_relay = {"CH1": None, "CH2": None}

        while True:
            try:
                r = requests.get(API_STATUS, timeout=2)
                r.raise_for_status()
                data = r.json()

                if not was_connected:
                    logging.info("Comunicazione con Backend stabilita.")
                    was_connected = True

                self.set_connection_state(True)

                # Estrai il blocco 'channels' dal JSON
                channels_data = data.get("channels", {})

                #
                ch1_data = channels_data.get("CH1", {})
                self.ch1.temp_label.configure(text=f"Temperatura: {round(ch1_data.get('temperature', '--'), 1)} °C")
                self.ch1.sp_curr_label.configure(text=f"Setpoint attuale: {ch1_data.get('setpoint', '--')} °C")
                self.ch1.hyst_curr_label.configure(text=f"Isteresi attuale: {ch1_data.get('hysteresis', '--')} °C")
                mode_label = "HEATING" if ch1_data.get("mode") == 1 else "COOLING"
                self.ch1.mode_curr_label.configure(text=f"Modalità: {mode_label}")
                relay_state = "ON" if ch1_data.get("relay", False) else "OFF"
                self.ch1.relay_label.configure(text=f"Relay: {relay_state}")

                # CH2
                ch2_data = channels_data.get("CH2", {})
                self.ch2.temp_label.configure(text=f"Temperatura: {round(ch2_data.get('temperature', '--'), 1)} °C")
                self.ch2.sp_curr_label.configure(text=f"Setpoint attuale: {ch2_data.get('setpoint', '--')} °C")
                self.ch2.hyst_curr_label.configure(text=f"Isteresi attuale: {ch2_data.get('hysteresis', '--')} °C")
                mode_label2 = "HEATING" if ch2_data.get("mode") == 1 else "COOLING"
                self.ch2.mode_curr_label.configure(text=f"Modalità: {mode_label2}")
                relay_state2 = "ON" if ch2_data.get("relay", False) else "OFF"
                self.ch2.relay_label.configure(text=f"Relay: {relay_state2}")

                # Log cambio di stato relè
                for ch_name in ["CH1", "CH2"]:
                    ch_info = channels_data.get(ch_name, {})
                    temp = ch_info.get('temperature', '--')
                    sp = ch_info.get('setpoint', '--')
                    relay_on = ch_info.get('relay', False)
                    if last_relay[ch_name] is not None and last_relay[ch_name] != relay_on:
                        stato_testo = "ON" if relay_on else "OFF"
                        logging.info(f"[{ch_name}] Cambio stato Relè: {stato_testo} (Temp: {temp}°C, Setpoint: {sp}°C)")
                    last_relay[ch_name] = relay_on

                # Disabling setpoint ctrl if scheduling enabled
                if ch1_data.get("schedule_enabled"):
                    self.ch1.sp_entry.configure(state="disabled")
                else:
                    self.ch1.sp_entry.configure(state="normal")
                if ch2_data.get("schedule_enabled"):
                    self.ch2.sp_entry.configure(state="disabled")
                else:
                    self.ch2.sp_entry.configure(state="normal")

            except Exception as e:
                if was_connected:
                    logging.error(f"Perdita comunicazione con Backend: {e}")
                    was_connected = False
                self.set_connection_state(False)

            time.sleep(1)

    def manual(self, state: bool):
        try:
            # Esempio per canale 1
            requests.post(f"http://{RASPBERRY_IP}:5000/manual/ch1", json={"state": state}, timeout=2)
            requests.post(f"http://{RASPBERRY_IP}:5000/manual/ch2", json={"state": state}, timeout=2)
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