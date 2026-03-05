import time
import threading
import json
import os
from datetime import datetime
from flask import Flask, jsonify, request
from gpiozero import OutputDevice
import spidev
import subprocess

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
            "manual_enable": False,
            "schedule_enabled": False,
            "schedule": []
        },
        "ch2": {
            "setpoint": 20.0,
            "hysteresis": 0.5,
            "mode": "heating",
            "enabled": True,
            "manual_enable": False,
            "schedule_enabled": False,
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
            data = json.load(f)

        # merge campi mancanti
        for ch in DEFAULT_CONFIG["channels"]:
            if ch not in data["channels"]:
                data["channels"][ch] = DEFAULT_CONFIG["channels"][ch]
            else:
                for key, val in DEFAULT_CONFIG["channels"][ch].items():
                    data["channels"][ch].setdefault(key, val)

        return data

    except Exception:
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

RELAY_ACTIVE_LOW = True
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
# CARICAMENTO CONFIG
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

POLL_INTERVAL = 1.0


# ==============================
# CONTROL LOOP
# ==============================

def control_loop():
    while True:
        try:
            now = datetime.now()

            for name, ch in channels.items():

                ch["temp"] = read_max6675(ch["spi"])

                # Modalità manuale per canale
                if ch["manual_enable"]:
                    continue

                # Determina setpoint attivo
                active_sp = ch["setpoint"]

                if ch["schedule_enabled"] and ch["schedule"]:
                    for item in ch["schedule"]:
                        start = datetime.fromisoformat(item["start"])
                        end = datetime.fromisoformat(item["end"])
                        if start <= now <= end:
                            active_sp = item["setpoint"]
                            break

                if not ch["enabled"] or ch["temp"] is None:
                    ch["relay"].off()
                    ch["output_on"] = False
                    continue

                sp = active_sp
                h = ch["hysteresis"]

                if ch["mode"] == "heating":
                    if ch["temp"] < sp - h:
                        ch["relay"].on()
                        ch["output_on"] = True
                    elif ch["temp"] >= sp:
                        ch["relay"].off()
                        ch["output_on"] = False

                elif ch["mode"] == "cooling":
                    if ch["temp"] > sp + h:
                        ch["relay"].on()
                        ch["output_on"] = True
                    elif ch["temp"] <= sp:
                        ch["relay"].off()
                        ch["output_on"] = False

        except Exception as e:
            print("Errore:", e)

        time.sleep(POLL_INTERVAL)


# ==============================
# FLASK
# ==============================

app = Flask(__name__)


@app.route("/status")
def status():
    return jsonify({
        "CH1": {
            "temperature": channels["ch1"]["temp"],
            "setpoint": channels["ch1"]["setpoint"],
            "hysteresis": channels["ch1"]["hysteresis"],
            "mode": 1 if channels["ch1"]["mode"] == "heating" else 2,
            "relay": channels["ch1"]["output_on"],
            "schedule_enabled": channels["ch1"]["schedule_enabled"]
        },
        "CH2": {
            "temperature": channels["ch2"]["temp"],
            "setpoint": channels["ch2"]["setpoint"],
            "hysteresis": channels["ch2"]["hysteresis"],
            "mode": 1 if channels["ch2"]["mode"] == "heating" else 2,
            "relay": channels["ch2"]["output_on"],
            "schedule_enabled": channels["ch2"]["schedule_enabled"]
        }
    })


@app.post("/settings")
def settings():
    data = request.json or {}

    for key, value in data.items():
        if key.startswith("CH1_"):
            ch = channels["ch1"]
            channel_name = "ch1"
        elif key.startswith("CH2_"):
            ch = channels["ch2"]
            channel_name = "ch2"
        else:
            continue

        param = key.split("_", 1)[1]

        if param == "setpoint":
            ch["setpoint"] = float(value)

        elif param == "hysteresis":
            ch["hysteresis"] = float(value)

        elif param == "mode":
            ch["mode"] = "heating" if int(value) == 1 else "cooling"

        elif param == "manual_enable":
            ch["manual_enable"] = bool(value)

        elif param == "schedule":
            # atteso formato:
            # [{"start": "...", "end": "...", "setpoint": 22.0}, ...]
            ch["schedule"] = value
            ch["schedule_enabled"] = True

        config_data["channels"][channel_name][param] = ch.get(param)

    save_config(config_data)

    return jsonify({"ok": True})


@app.post("/manual")
def manual():
    data = request.json or {}

    for key, value in data.items():
        if key.startswith("CH1_"):
            ch = channels["ch1"]
        elif key.startswith("CH2_"):
            ch = channels["ch2"]
        else:
            continue

        if key.endswith("_on"):
            if value:
                ch["relay"].on()
            else:
                ch["relay"].off()

            ch["output_on"] = bool(value)

    return jsonify({"ok": True})


@app.post("/shutdown")
def shutdown():
    subprocess.Popen(["sudo", "shutdown", "-h", "now"])
    return jsonify({"ok": True})


# ==============================
# AVVIO
# ==============================

if __name__ == "__main__":
    thread = threading.Thread(target=control_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5000)