import time
import threading
import json
import os
from flask import Flask, jsonify, request
from gpiozero import OutputDevice
import spidev
from datetime import datetime

# ==============================
# CONFIG FILE
# ==============================

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "channels": {
        "ch1": {
            "setpoint": 20.0,
            "hysteresis": 0.5,
            "mode": "heating",
            "enabled": True,
            "schedule": []  # tuple list [ [start_iso, end_iso, setpoint], ... ]
        },
        "ch2": {
            "setpoint": 20.0,
            "hysteresis": 0.5,
            "mode": "heating",
            "enabled": True,
            "schedule": []
        }
    }
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

def save_config(data):
    tmp_file = CONFIG_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, CONFIG_FILE)

# ==============================
# HARDWARE
# ==============================

RELAY_ACTIVE_LOW = False
SPI_BUS = 0

CH1_PIN = 17
CH2_PIN = 27

ch1_relay = OutputDevice(CH1_PIN, active_high=not RELAY_ACTIVE_LOW, initial_value=False)
ch2_relay = OutputDevice(CH2_PIN, active_high=not RELAY_ACTIVE_LOW, initial_value=False)

spi_ch1 = spidev.SpiDev()
spi_ch1.open(SPI_BUS, 0)
spi_ch1.max_speed_hz = 500000

spi_ch2 = spidev.SpiDev()
spi_ch2.open(SPI_BUS, 1)
spi_ch2.max_speed_hz = 500000

def read_max6675(spi):
    raw = spi.xfer2([0x00, 0x00])
    value = (raw[0] << 8) | raw[1]
    if value & 0x4:
        return None
    return (value >> 3) * 0.25

# ==============================
# CONFIG LOADING
# ==============================

config_data = load_config()

channels = {
    "ch1": {
        "temp": None,
        "relay": ch1_relay,
        "spi": spi_ch1,
        "output_on": False,
        **config_data["channels"]["ch1"]
    },
    "ch2": {
        "temp": None,
        "relay": ch2_relay,
        "spi": spi_ch2,
        "output_on": False,
        **config_data["channels"]["ch2"]
    }
}

manual_enabled = False
POLL_INTERVAL = 1.0

# ==============================
# CONTROL LOOP
# ==============================

def control_loop():
    while True:
        try:
            # 1. Lettura dei sensori
            t1 = read_max6675(spi_ch1)
            t2 = 20.0  # Valore fisso per test

            # 2. Aggiornamento immediato del dizionario
            channels["ch1"]["temp"] = t1
            channels["ch2"]["temp"] = t2

            now = datetime.now()

            # 3. Logica di controllo per ogni canale
            for name, ch in channels.items():
                # Se la modalità manuale è attiva, non fare nulla (decide l'utente)
                if manual_enabled:
                    continue

                # Protezione: se il canale è disattivato o la sonda legge None
                if not ch.get("enabled", True) or ch["temp"] is None:
                    ch["relay"].off()
                    ch["output_on"] = False
                    continue

                # Controllo Programmazione (Scheduling)
                current_setpoint = ch["setpoint"]
                has_active_schedule = False

                for entry in ch.get("schedule", []):
                    start_dt = datetime.fromisoformat(entry[0])
                    end_dt = datetime.fromisoformat(entry[1])
                    if start_dt <= now <= end_dt:
                        current_setpoint = entry[2]
                        has_active_schedule = True
                        break

                # Se non c'è uno schedule attivo, puliamo la variabile temporanea
                if has_active_schedule:
                    ch["active_setpoint"] = current_setpoint
                else:
                    ch.pop("active_setpoint", None)

                h = ch["hysteresis"]
                temp = ch["temp"]

                # Logica Termostato
                if ch["mode"] == "heating":
                    if temp < current_setpoint - h:
                        ch["relay"].on()
                        ch["output_on"] = True
                    elif temp >= current_setpoint:
                        ch["relay"].off()
                        ch["output_on"] = False
                elif ch["mode"] == "cooling":
                    if temp > current_setpoint + h:
                        ch["relay"].on()
                        ch["output_on"] = True
                    elif temp <= current_setpoint:
                        ch["relay"].off()
                        ch["output_on"] = False

        except Exception as e:
            print(f"Errore nel ciclo di controllo: {e}")

        time.sleep(POLL_INTERVAL)

# ==============================
# FLASK
# ==============================

app = Flask(__name__)

@app.route("/status")
def status():
    return jsonify({
        "manual": manual_enabled,
        "channels": {
            name.upper(): {
                "temperature": ch["temp"],
                "setpoint": ch.get("active_setpoint", ch["setpoint"]),
                "hysteresis": ch["hysteresis"],
                "mode": 1 if ch["mode"]=="heating" else 2,
                "enabled": ch["enabled"],
                "relay": ch["output_on"],
                "schedule_enabled": len(ch.get("schedule", []))>0
            }
            for name, ch in channels.items()
        }
    })

@app.post("/settings")
@app.post("/settings")
def settings():
    data = request.json
    if not data:
        return jsonify({"error": "No data received"}), 400

    # Mappatura tra i nomi del Frontend (CH1_...) e le chiavi del Backend (ch1)
    mapping = {
        "CH1": "ch1",
        "CH2": "ch2"
    }

    for front_prefix, back_id in mapping.items():
        # Aggiornamento Setpoint
        if f"{front_prefix}_setpoint" in data:
            try:
                new_sp = float(data[f"{front_prefix}_setpoint"])
                config_data["channels"][back_id]["setpoint"] = new_sp

                # Svuota lo scheduling perché l'utente ha preso il controllo
                config_data["channels"][back_id]["schedule"] = []
                channels[back_id]["schedule"] = []
                # Rimuove anche il setpoint attivo temporaneo
                if "active_setpoint" in channels[back_id]:
                    del channels[back_id]["active_setpoint"]
            except ValueError:
                pass

        # Aggiornamento Isteresi
        if f"{front_prefix}_hysteresis" in data:
            try:
                config_data["channels"][back_id]["hysteresis"] = float(data[f"{front_prefix}_hysteresis"])
            except ValueError:
                pass

        # Aggiornamento Modalità (1 = heating, 2 = cooling)
        if f"{front_prefix}_mode" in data:
            val = data[f"{front_prefix}_mode"]
            config_data["channels"][back_id]["mode"] = "heating" if val == 1 else "cooling"

        # Aggiornamento Stato Abilitazione (On/Off generale del canale)
        if f"{front_prefix}_enabled" in data:
            config_data["channels"][back_id]["enabled"] = bool(data[f"{front_prefix}_enabled"])

    # Salvataggio persistente su config.json
    save_config(config_data)

    # Sincronizzazione immediata della variabile di runtime 'channels' usata dal loop
    for ch_id in ["ch1", "ch2"]:
        channels[ch_id]["setpoint"] = config_data["channels"][ch_id]["setpoint"]
        channels[ch_id]["hysteresis"] = config_data["channels"][ch_id]["hysteresis"]
        channels[ch_id]["mode"] = config_data["channels"][ch_id]["mode"]
        channels[ch_id]["enabled"] = config_data["channels"][ch_id]["enabled"]

    return jsonify({"ok": True})

@app.post("/manual")
def manual():
    global manual_enabled
    data = request.json or {}
    manual_enabled = bool(data.get("manual", False))
    if not manual_enabled:
        for ch in channels.values():
            ch["relay"].off()
            ch["output_on"] = False
    return jsonify({"ok": True})

@app.post("/manual/<channel>")
def manual_ch(channel):
    if channel not in channels:
        return jsonify({"error": "invalid channel"}), 404
    if not manual_enabled:
        return jsonify({"error": "manual mode disabled"}), 400
    state = bool(request.json.get("state", False))
    ch = channels[channel]
    if state:
        ch["relay"].on()
    else:
        ch["relay"].off()
    ch["output_on"] = state
    return jsonify({"ok": True})

@app.post("/schedule/<channel>")
def schedule_ch(channel):
    if channel not in channels:
        return jsonify({"error": "invalid channel"}), 404
    data = request.json or {}
    schedule_list = []
    for entry in data.get("schedule", []):
        # list [start_iso, end_iso, setpoint]
        try:
            start_dt = datetime.fromisoformat(entry[0])
            end_dt = datetime.fromisoformat(entry[1])
            sp = float(entry[2])
            schedule_list.append([start_dt.isoformat(), end_dt.isoformat(), sp])
        except:
            continue
    channels[channel]["schedule"] = schedule_list

    # Persistent config update
    config_data["channels"][channel]["schedule"] = schedule_list
    save_config(config_data)
    return jsonify({"ok": True})

@app.post("/shutdown")
def shutdown():
    # Relays OFF
    for ch in channels.values():
        ch["relay"].off()
        ch["output_on"] = False
    # RPi Shutdown
    os.system("sudo shutdown now")
    return jsonify({"ok": True})

# ==============================
# AVVIO
# ==============================

if __name__ == "__main__":
    thread = threading.Thread(target=control_loop, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=5000)