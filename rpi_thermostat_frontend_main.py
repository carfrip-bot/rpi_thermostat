import customtkinter as ctk
from CTkMessagebox import CTkMessagebox
import threading
import time
import uuid
from datetime import datetime, timezone
from tkcalendar import Calendar
import logging
import json
import os
from pathlib import Path

from firebase_client import FirebaseDatabaseError, FirebaseRealtimeDatabase

APP_DIR = Path(__file__).resolve().parent
DATABASE = FirebaseRealtimeDatabase()


class ConfigSyncPendingError(FirebaseDatabaseError):
    """The desired settings reached Firebase, but local Pi persistence is pending."""

# --- MACHINE DATA LOADING FROM FILE ---
def load_machine_data():
    settings_file = APP_DIR / "machine_data.json"
    machine_data = {
        "status_timeout": 10.0,
        "status_poll_interval": 1.0,
    }
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                data = json.load(f)
                machine_data["status_timeout"] = float(data.get("status_timeout", machine_data["status_timeout"]))
                machine_data["status_poll_interval"] = float(
                    data.get("status_poll_interval", machine_data["status_poll_interval"])
                )
        except Exception as e:
            print(f"Errore lettura machine_data.json: {e}")
    return machine_data

machine_data = load_machine_data()
STATUS_TIMEOUT = machine_data.get("status_timeout", 10.0)
STATUS_POLL_INTERVAL = machine_data.get("status_poll_interval", 1.0)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_FONT = "Bahnschrift"
CALENDAR_FONT = "Bahnschrift 24"
GLOBAL_FONT = (APP_FONT, 14)

logging.basicConfig(
    filename=str(APP_DIR / 'log.txt'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logging.info("=== Applicazione Termostato Avviata ===")

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

def center_window(win):
    win.update_idletasks()
    width = win.winfo_width()
    height = win.winfo_height()
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height * 2)
    win.geometry(f"+{x}+{y}")

# --- Channel Frame for CH1 and CH2 ---
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
        self.app = parent.winfo_toplevel()
        label_font = (APP_FONT, 16)

        header_text = title if title is not None else f"CH{ch_num}"
        self.header = ctk.CTkFrame(self, fg_color=header_fg, corner_radius=10)
        self.header.pack(fill="x", padx=0, pady=(0, 6))

        self.header_content = ctk.CTkFrame(self.header, fg_color="transparent")
        self.header_content.pack(expand=True)

        self.header_label = ctk.CTkLabel(
            self.header_content,
            text=f"{header_text}   •   ",
            font=(APP_FONT, 20, "bold"),
            text_color="#FFF4B0"
        )
        self.header_label.pack(side="left", pady=6)

        self.header_temp_label = ctk.CTkLabel(
            self.header_content,
            text="-- °C",
            font=(APP_FONT, 20, "bold"),
            text_color="#FFF4B0"
        )
        self.header_temp_label.pack(side="left", pady=6)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.left_col = ctk.CTkFrame(self.body, fg_color="transparent")
        self.left_col.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        self.right_col = ctk.CTkFrame(self.body, fg_color="transparent")
        self.right_col.pack(side="right", fill="both", expand=True, padx=10, pady=10)

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

        self.manual_enable_var = ctk.IntVar(value=0)
        self.manual_cb = ctk.CTkCheckBox(
            self.left_col,
            text="Attiva forzatura",
            variable=self.manual_enable_var,
            command=self.manual_enable_toggle,
            font=GLOBAL_FONT
        )
        self.manual_cb.grid(row=3, column=0, columnspan=3, sticky="w", padx=5, pady=(10, 5))

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

        self.update_manual_buttons_state()

        self.sp_curr_label = ctk.CTkLabel(self.right_col, text="Setpoint attuale: --", font=label_font)
        self.sp_curr_label.pack(pady=5)

        self.hyst_curr_label = ctk.CTkLabel(self.right_col, text="Isteresi attuale: --", font=label_font)
        self.hyst_curr_label.pack(pady=5)

        self.mode_curr_label = ctk.CTkLabel(self.right_col, text="Modalità: --", font=label_font)
        self.mode_curr_label.pack(pady=5)

        self.relay_label = ctk.CTkLabel(self.right_col, text="Relay: --", font=label_font)
        self.relay_label.pack(pady=5)

        self.sp_entry.bind("<Button-1>", lambda e: open_numeric_pad(self, self.sp_entry))
        self.hyst_entry.bind("<Button-1>", lambda e: open_numeric_pad(self, self.hyst_entry))

    def update_settings(self, param=None):
        prefix = f"CH{self.ch_num}_"

        if param == "setpoint" and getattr(self, "is_planning_active", False):
            msg = CTkMessagebox(
                title="Conferma Setpoint Diretto",
                message=f"È attivo un planning su {prefix[:-1]}.\nVuoi procedere?",
                icon="warning",
                option_1="Annulla",
                option_2="Si, procedi",
                width=450,
                height=180,
                button_height=30,
                button_width=110,
                corner_radius=10,
                font=(APP_FONT, 14),
                justify="center"
            )
            if msg.get() == "Annulla":
                return
        try:
            updates = {}

            if param == "setpoint" or param is None:
                updates["setpoint"] = float(self.sp_entry.get())

            if param == "hysteresis" or param is None:
                updates["hysteresis"] = float(self.hyst_entry.get())

            if param == "mode" or param is None:
                mode_num = float(self.mode_var.get().split(" ")[0])
                updates["mode"] = "heating" if mode_num == 1 else "cooling"

            if updates:
                self.app.update_channel_config(self.ch_num, updates, clear_schedule=("setpoint" in updates))
                logging.info("Configurazione CH%s inviata a Firebase: %s", self.ch_num, updates)
        except Exception as e:
            logging.error("Errore aggiornamento CH%s: %s", self.ch_num, e)
            if isinstance(e, ConfigSyncPendingError):
                message = f"Le impostazioni sono su Firebase, ma manca ancora la conferma del salvataggio locale sul Raspberry.\n{e}"
            else:
                message = f"Impossibile salvare le impostazioni su Firebase.\n{e}"
            CTkMessagebox(title="Errore", message=message, icon="cancel")

    def manual_enable_toggle(self):
        try:
            val = bool(self.manual_enable_var.get())
            self.app.send_firebase_command("manual_enabled", val)
        except Exception as e:
            logging.error("Errore comando modalità manuale CH%s: %s", self.ch_num, e)

        self.update_manual_buttons_state()

    def update_manual_buttons_state(self):
        enabled = bool(self.manual_enable_var.get())
        state = "normal" if enabled else "disabled"
        self.on_btn.configure(state=state)
        self.off_btn.configure(state=state)

    def manual_set(self, state: bool):
        try:
            self.app.send_firebase_command(f"manual_relay/ch{self.ch_num}", state)
        except Exception as e:
            logging.error("Errore comando manuale CH%s: %s", self.ch_num, e)

    def open_plan_popup(self):
        channel = self.ch_num
        popup = ctk.CTkToplevel(self)
        popup.title(f"Pianificazione CH{channel}")
        popup.geometry("650x650")
        center_window(popup)
        popup.lift()
        popup.focus_force()
        popup.grab_set()
        popup.attributes("-topmost", True)
        popup.after(200, lambda: popup.attributes("-topmost", False))

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

        def mark_row_invalid(index):
            if index < len(container.winfo_children()):
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

            for i, (start_var, sp_var) in enumerate(entries):
                try:
                    start_dt = datetime.strptime(start_var.get(), "%d/%m/%Y %H:%M")
                    sp_val = float(sp_var.get())
                    parsed_rows.append((start_dt, sp_val))
                except Exception:
                    valid = False
                    continue

            if len(parsed_rows) != len(entries) or len(parsed_rows) == 0:
                valid = False

            for i in range(len(parsed_rows) - 1):
                if parsed_rows[i][0] >= parsed_rows[i + 1][0]:
                    valid = False
                    mark_row_invalid(i)
                    mark_row_invalid(i + 1)

            try:
                confirm_button.configure(state="normal" if valid else "disabled")
            except NameError:
                pass

        def _on_var_change(name: str, index: str, mode: str) -> None:
            validate_plan()

        def confirm_plan():
            parsed = []

            for start_var, sp_var in entries:
                try:
                    start_dt = datetime.strptime(start_var.get(), "%d/%m/%Y %H:%M")
                    setpoint = float(sp_var.get())
                    parsed.append((start_dt, setpoint))
                except Exception as e:
                    print(f"Errore parsing plan: {e}")
                    return

            if not parsed:
                return

            plan_data = []
            for i in range(len(parsed)):
                start_dt, setpoint = parsed[i]
                if i < len(parsed) - 1:
                    end_dt = parsed[i + 1][0]
                else:
                    end_dt = datetime(2099, 12, 31, 23, 59)

                plan_data.append([start_dt.isoformat(), end_dt.isoformat(), setpoint])

            try:
                self.app.update_channel_config(channel, {"schedule": plan_data})
                logging.info(f"Inviato nuovo SCHEDULING per Canale {channel}: {plan_data}")
            except Exception as e:
                logging.error("Errore nell'invio dello SCHEDULING per Canale %s: %s", channel, e)
                if isinstance(e, ConfigSyncPendingError):
                    message = f"Il planning è su Firebase, ma il Raspberry non ha ancora confermato il salvataggio locale.\n{e}"
                else:
                    message = f"Impossibile salvare il planning su Firebase.\n{e}"
                CTkMessagebox(
                    title="Errore",
                    message=message + "\n\nIl planning è ancora aperto.",
                    icon="cancel",
                )
                return

            popup.destroy()

        confirm_button = ctk.CTkButton(
            popup,
            text="Conferma Pianificazione",
            command=confirm_plan,
            state="disabled"
        )
        confirm_button.pack(pady=20)

        def rebuild_intervals():
            for widget in container.winfo_children():
                widget.destroy()
            entries.clear()

            try:
                count = int(count_var.get())
            except Exception:
                return

            for i in range(count):
                row = ctk.CTkFrame(container)
                row.pack(fill="x", pady=5)

                row.grid_columnconfigure(1, weight=1)
                row.grid_columnconfigure(2, weight=1)

                interval_label = ctk.CTkLabel(row, text=f"Intervallo {i + 1}")
                interval_label.grid(row=0, column=0, padx=5)

                start_var = ctk.StringVar()
                setpoint_var = ctk.StringVar()

                def open_calendar(d_var):
                    cal_popup = ctk.CTkToplevel(popup)
                    cal_popup.title("Seleziona data e ora inizio")
                    cal_popup.geometry("550x650")
                    center_window(cal_popup)
                    cal_popup.minsize(550, 650)
                    cal_popup.transient(popup)
                    cal_popup.grab_set()

                    cal = Calendar(cal_popup, date_pattern="dd/mm/yyyy", font=CALENDAR_FONT, locale='it_IT')
                    cal.pack(pady=10, expand=True, fill="both")

                    time_frame = ctk.CTkFrame(cal_popup, fg_color="transparent")
                    time_frame.pack(pady=10)

                    ctk.CTkLabel(time_frame, text="Ora:", font=GLOBAL_FONT).pack(side="left", padx=5)
                    hours_var = ctk.StringVar(value="00")
                    hours_menu = ctk.CTkOptionMenu(
                        time_frame,
                        values=[f"{h:02d}" for h in range(24)],
                        variable=hours_var,
                        width=70,
                        font=GLOBAL_FONT
                    )
                    hours_menu.pack(side="left", padx=5)

                    ctk.CTkLabel(time_frame, text="Minuti:", font=GLOBAL_FONT).pack(side="left", padx=5)
                    mins_var = ctk.StringVar(value="00")
                    mins_menu = ctk.CTkOptionMenu(
                        time_frame,
                        values=[f"{m:02d}" for m in range(0, 60, 5)],
                        variable=mins_var,
                        width=70,
                        font=GLOBAL_FONT
                    )
                    mins_menu.pack(side="left", padx=5)

                    def confirm_date():
                        d_var.set(f"{cal.get_date()} {hours_var.get()}:{mins_var.get()}")
                        cal_popup.destroy()

                    confirm_btn = ctk.CTkButton(cal_popup, text="OK", command=confirm_date, font=GLOBAL_FONT)
                    confirm_btn.pack(pady=10)

                start_entry = ctk.CTkEntry(row, textvariable=start_var)
                start_entry.grid(row=0, column=1, padx=5, sticky="ew")
                add_placeholder(start_entry, "Inizio (gg/mm/aaaa hh:mm)")
                start_entry.bind("<Button-1>", lambda e, dv=start_var: open_calendar(dv))

                start_var.trace_add("write", _on_var_change)
                setpoint_var.trace_add("write", _on_var_change)

                setpoint_entry = ctk.CTkEntry(row, textvariable=setpoint_var)
                setpoint_entry.grid(row=0, column=2, padx=5, sticky="ew")
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

                entries.append((start_var, setpoint_var))

            validate_plan()

        rebuild_intervals()

# --- Main App ---
class ThermostatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Termostato")
        self.geometry("1400x500")
        self.iconbitmap(str(APP_DIR / "rpi_thermostat.ico"))
        self.update_msg = ctk.CTkLabel(self, text="", font=GLOBAL_FONT, text_color="green")
        self.update_msg.pack(pady=5)

        self.connected = False
        self.last_status = None
        self.last_relay = {"CH1": None, "CH2": None}
        self._initial_settings_loaded = False
        self.connection_label = ctk.CTkLabel(
            self,
            text="TERMOSTATO OFFLINE",
            font=(APP_FONT, 25, "bold"),
            text_color="red"
        )
        self.connection_label.pack(pady=5)

        self.channels_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.channels_frame.pack(fill="both", expand=True, padx=20, pady=10)

        self.ch1 = ChannelFrame(self.channels_frame, 1, title="CHANNEL 1")
        self.ch1.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        self.ch2 = ChannelFrame(self.channels_frame, 2, title="CHANNEL 2")
        self.ch2.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        self.shutdown_btn = ctk.CTkButton(self, text="Spegni Termostato", command=self.shutdown_rpi, font=(APP_FONT, 18))
        self.shutdown_btn.pack(side="bottom", pady=10)

        threading.Thread(target=self.update_loop, daemon=True).start()

    def set_connection_state(self, state: bool):
        if state == self.connected:
            return

        self.connected = state

        if state:
            self.connection_label.configure(text="TERMOSTATO ONLINE", text_color="green")
        else:
            self.connection_label.configure(text="TERMOSTATO OFFLINE", text_color="red")

            for ch in [self.ch1, self.ch2]:
                ch.header_temp_label.configure(text="-- °C")
                ch.sp_curr_label.configure(text="Setpoint attuale: --")
                ch.hyst_curr_label.configure(text="Isteresi attuale: --")
                ch.mode_curr_label.configure(text="Modalità: --")
                ch.relay_label.configure(text="Relay: --")

    def update_loop(self):
        was_connected = True

        while True:
            try:
                data = DATABASE.get("thermostat/status")
                if not isinstance(data, dict):
                    raise FirebaseDatabaseError("Stato del Raspberry non ancora disponibile")

                updated_at = data.get("updated_at")
                if not updated_at:
                    raise FirebaseDatabaseError("Lo stato Firebase non contiene il timestamp di aggiornamento")
                state_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - state_time).total_seconds()
                if age_seconds < -60 or age_seconds > STATUS_TIMEOUT:
                    raise FirebaseDatabaseError("Stato del Raspberry non aggiornato")

                if not was_connected:
                    logging.info("Comunicazione con Raspberry/Firebase stabilita.")
                    was_connected = True

                self.last_status = data
                self.after(0, self.apply_status, data)

            except Exception as e:
                if was_connected:
                    logging.error("Perdita comunicazione con Raspberry/Firebase: %s", e)
                    was_connected = False
                self.last_status = None
                self.after(0, self.set_connection_state, False)

            time.sleep(STATUS_POLL_INTERVAL)

    def apply_status(self, data):
        self.set_connection_state(True)
        channels_data = data.get("channels", {})
        channel_frames = {"CH1": self.ch1, "CH2": self.ch2}

        if not self._initial_settings_loaded:
            for channel_name, frame in channel_frames.items():
                channel_data = channels_data.get(channel_name, {})
                if channel_data.get("setpoint") is not None:
                    frame.sp_entry.insert(0, str(channel_data["setpoint"]))
                if channel_data.get("hysteresis") is not None:
                    frame.hyst_entry.insert(0, str(channel_data["hysteresis"]))
                frame.mode_var.set("1 - HEATING" if channel_data.get("mode") == 1 else "2 - COOLING")
            self._initial_settings_loaded = True

        for channel_name, frame in channel_frames.items():
            channel_data = channels_data.get(channel_name, {})
            raw_temperature = channel_data.get("temperature")
            temperature = round(raw_temperature, 1) if raw_temperature is not None else "--"
            frame.header_temp_label.configure(text=f"{temperature} °C")
            frame.sp_curr_label.configure(text=f"Setpoint attuale: {channel_data.get('setpoint', '--')} °C")
            frame.hyst_curr_label.configure(text=f"Isteresi attuale: {channel_data.get('hysteresis', '--')} °C")
            mode_label = "HEATING" if channel_data.get("mode") == 1 else "COOLING"
            frame.mode_curr_label.configure(text=f"Modalità: {mode_label}")
            relay_on = channel_data.get("relay", False)
            frame.relay_label.configure(text=f"Relay: {'ON' if relay_on else 'OFF'}")
            frame.is_planning_active = channel_data.get("schedule_enabled", False)
            frame.sp_entry.configure(
                state="normal",
                fg_color=("#F9F9FA", "#343638") if not frame.is_planning_active else "#3b3b00",
            )

            if self.last_relay[channel_name] is not None and self.last_relay[channel_name] != relay_on:
                logging.info(
                    "[%s] Cambio stato Relè: %s (Temp: %s°C, Setpoint: %s°C)",
                    channel_name,
                    "ON" if relay_on else "OFF",
                    channel_data.get("temperature", "--"),
                    channel_data.get("setpoint", "--"),
                )
            self.last_relay[channel_name] = relay_on

        manual_enabled = bool(data.get("manual", False))
        for frame in channel_frames.values():
            frame.manual_enable_var.set(1 if manual_enabled else 0)
            frame.update_manual_buttons_state()

    def update_channel_config(self, channel_number, updates, clear_schedule=False):
        current = DATABASE.get("thermostat/config")
        if not isinstance(current, dict):
            current = {
                "revision": 0,
                "channels": {
                    "ch1": {"setpoint": 20.0, "hysteresis": 0.5, "mode": "heating", "enabled": True, "schedule": []},
                    "ch2": {"setpoint": 20.0, "hysteresis": 0.5, "mode": "heating", "enabled": True, "schedule": []},
                },
            }

        channel_id = f"ch{channel_number}"
        channels_config = current.setdefault("channels", {})
        channel_config = channels_config.setdefault(
            channel_id,
            {"setpoint": 20.0, "hysteresis": 0.5, "mode": "heating", "enabled": True, "schedule": []},
        )
        channel_config.update(updates)
        if clear_schedule:
            channel_config["schedule"] = []

        current["revision"] = max(int(current.get("revision", 0)) + 1, int(time.time() * 1000))
        current["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        DATABASE.put("thermostat/config", current)

        # Treat a settings change as complete only after the Raspberry has
        # persisted that revision to its local config.json and published the ack.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            try:
                status = DATABASE.get("thermostat/status")
            except FirebaseDatabaseError as exc:
                raise ConfigSyncPendingError(
                    f"La revisione {current['revision']} è su Firebase, ma non è possibile verificare il salvataggio locale: {exc}"
                ) from exc
            if isinstance(status, dict) and int(status.get("config_revision", -1)) >= current["revision"]:
                return current
            time.sleep(0.5)

        raise ConfigSyncPendingError(
            f"La revisione {current['revision']} è su Firebase, ma il Raspberry non ha ancora confermato il salvataggio locale"
        )

    def send_firebase_command(self, path, value):
        if not self.last_status or not self.last_status.get("boot_id"):
            raise FirebaseDatabaseError("Il Raspberry non risulta connesso: attendi che torni online")
        command = {
            "id": uuid.uuid4().hex,
            "boot_id": self.last_status["boot_id"],
            "value": value,
        }
        DATABASE.put(f"thermostat/commands/{path}", command)

    def shutdown_rpi(self):
        try:
            msg = CTkMessagebox(title="Conferma", message="Spegni RPi?", icon="warning", option_1="No", option_2="Sì")
            if msg.get() == "Sì":
                self.send_firebase_command("shutdown", True)
        except Exception as e:
            logging.error("Errore invio comando di spegnimento: %s", e)
            CTkMessagebox(title="Errore", message=f"Impossibile inviare il comando di spegnimento.\n{e}", icon="cancel")

def main():
    app = ThermostatApp()
    app.mainloop()

if __name__ == "__main__":
    main()
