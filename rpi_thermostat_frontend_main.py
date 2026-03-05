import customtkinter as ctk
from CTkMessagebox import CTkMessagebox
import requests
import threading
import time

RASPBERRY_IP = "192.168.68.128"
API_STATUS = f"http://{RASPBERRY_IP}:5000/status"
API_CONFIG = f"http://{RASPBERRY_IP}:5000/config"
API_MANUAL_MODE = f"http://{RASPBERRY_IP}:5000/manual_mode"
API_MANUAL = f"http://{RASPBERRY_IP}:5000/manual"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_FONT = "Bahnschrift"
GLOBAL_FONT = (APP_FONT, 14)


class ChannelFrame(ctk.CTkFrame):
    def __init__(self, master, channel_name):
        super().__init__(master)
        self.channel = channel_name

        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(self, text=channel_name.upper(), font=(APP_FONT, 20))
        title.grid(row=0, column=0, columnspan=2, pady=10)

        # --- COLONNA SINISTRA (SCRITTURA) ---
        write_frame = ctk.CTkFrame(self)
        write_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        write_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(write_frame, text="SETTINGS", font=(APP_FONT, 16)).grid(
            row=0, column=0, columnspan=2, pady=5
        )

        ctk.CTkLabel(write_frame, text="Setpoint °C", font=GLOBAL_FONT).grid(row=1, column=0, sticky="w")
        self.setpoint_entry = ctk.CTkEntry(write_frame)
        self.setpoint_entry.grid(row=1, column=1, pady=2, sticky="ew")

        ctk.CTkLabel(write_frame, text="Isteresi °C", font=GLOBAL_FONT).grid(row=2, column=0, sticky="w")
        self.hysteresis_entry = ctk.CTkEntry(write_frame)
        self.hysteresis_entry.grid(row=2, column=1, pady=2, sticky="ew")

        ctk.CTkLabel(write_frame, text="Modalità", font=GLOBAL_FONT).grid(row=3, column=0, sticky="w")
        self.mode_var = ctk.StringVar(value="heating")
        self.mode_menu = ctk.CTkOptionMenu(
            write_frame,
            values=["heating", "cooling"],
            variable=self.mode_var
        )
        self.mode_menu.grid(row=3, column=1, pady=2, sticky="ew")

        self.enable_var = ctk.IntVar(value=1)
        self.enable_cb = ctk.CTkCheckBox(write_frame, text="Abilitato", variable=self.enable_var)
        self.enable_cb.grid(row=4, column=0, columnspan=2, pady=5)

        ctk.CTkButton(
            write_frame,
            text="Applica",
            command=self.apply_config
        ).grid(row=5, column=0, columnspan=2, pady=5)

        # --- COLONNA DESTRA (LETTURA) ---
        read_frame = ctk.CTkFrame(self)
        read_frame.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        read_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(read_frame, text="STATUS", font=(APP_FONT, 16)).grid(
            row=0, column=0, pady=5
        )

        self.temp_label = ctk.CTkLabel(read_frame, text="Temp attuale: -- °C")
        self.temp_label.grid(row=1, column=0, pady=2)

        self.sp_label = ctk.CTkLabel(read_frame, text="Setpoint attuale: --")
        self.sp_label.grid(row=2, column=0, pady=2)

        self.hyst_label = ctk.CTkLabel(read_frame, text="Isteresi attuale: --")
        self.hyst_label.grid(row=3, column=0, pady=2)

        self.mode_label = ctk.CTkLabel(read_frame, text="Modalità attuale: --")
        self.mode_label.grid(row=4, column=0, pady=2)

        self.output_label = ctk.CTkLabel(read_frame, text="Relè: --")
        self.output_label.grid(row=5, column=0, pady=5)

        # --- MANUAL BUTTONS (FUORI DALLE COLONNE) ---
        manual_frame = ctk.CTkFrame(self)
        manual_frame.grid(row=2, column=0, columnspan=2, pady=10)

        ctk.CTkButton(
            manual_frame,
            text="ON",
            width=80,
            command=lambda: self.manual(True)
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            manual_frame,
            text="OFF",
            width=80,
            command=lambda: self.manual(False)
        ).pack(side="left", padx=10)

    def apply_config(self):
        try:
            payload = {
                "setpoint": float(self.setpoint_entry.get()),
                "hysteresis": float(self.hysteresis_entry.get()),
                "mode": self.mode_var.get(),
                "enabled": bool(self.enable_var.get())
            }
            requests.post(f"{API_CONFIG}/{self.channel}", json=payload, timeout=2)
        except:
            pass

    def manual(self, state):
        try:
            requests.post(
                f"{API_MANUAL}/{self.channel}",
                json={"state": state},
                timeout=2
            )
        except:
            pass

    def update_state(self, data):
        temp = data.get("temp")

        if temp is not None:
            self.temp_label.configure(text=f"Temp attuale: {temp:.2f} °C")
        else:
            self.temp_label.configure(text="Temp attuale: -- °C")

        self.sp_label.configure(text=f"Setpoint attuale: {data.get('setpoint')}")
        self.hyst_label.configure(text=f"Isteresi attuale: {data.get('hysteresis')}")
        self.mode_label.configure(text=f"Modalità attuale: {data.get('mode')}")
        self.output_label.configure(
            text=f"Relè: {'ON' if data.get('output_on') else 'OFF'}"
        )


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Termostato Dual Channel")
        self.geometry("1200x500")

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.ch1 = ChannelFrame(self, "ch1")
        self.ch1.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        self.ch2 = ChannelFrame(self, "ch2")
        self.ch2.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        # Manual mode globale
        self.manual_global = ctk.IntVar(value=0)
        ctk.CTkCheckBox(
            self,
            text="Manual Mode Globale",
            variable=self.manual_global,
            command=self.toggle_manual
        ).grid(row=1, column=0, columnspan=2, pady=10)

        self.conn_label = ctk.CTkLabel(self, text="DISCONNESSO", text_color="red")
        self.conn_label.grid(row=2, column=0, columnspan=2)

        threading.Thread(target=self.update_loop, daemon=True).start()

    def toggle_manual(self):
        try:
            requests.post(
                API_MANUAL_MODE,
                json={"enabled": bool(self.manual_global.get())},
                timeout=2
            )
        except:
            pass

    def update_loop(self):
        while True:
            try:
                r = requests.get(API_STATUS, timeout=2)
                data = r.json()

                self.ch1.update_state(data["channels"]["ch1"])
                self.ch2.update_state(data["channels"]["ch2"])

                self.manual_global.set(1 if data.get("manual") else 0)

                self.conn_label.configure(text="CONNESSO", text_color="green")

            except:
                self.conn_label.configure(text="DISCONNESSO", text_color="red")

            time.sleep(1)


if __name__ == "__main__":
    app = App()
    app.mainloop()