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
            now = datetime.now()
            for name, ch in channels.items():
                ch["temp"] = read_max6675(ch["spi"])

                if manual_enabled:
                    continue

                if not ch["enabled"] or ch["temp"] is None:
                    ch["relay"].off()
                    ch["output_on"] = False
                    continue

                # Check: scheduling active?
                schedule_setpoint = None
                for entry in ch.get("schedule", []):
                    start_dt = datetime.fromisoformat(entry[0])
                    end_dt = datetime.fromisoformat(entry[1])
                    sp = entry[2]
                    if start_dt <= now <= end_dt:
                        schedule_setpoint = sp
                        break

                sp = schedule_setpoint if schedule_setpoint is not None else ch["setpoint"]
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
        "manual": manual_enabled,
        "channels": {
            name.upper(): {
                "temperature": ch["temp"],
                "setpoint": ch["setpoint"],
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
def settings():
    data = request.json or {}
    for name, ch in channels.items():
        prefix = name.upper() + "_"
        if prefix + "setpoint" in data:
            ch["setpoint"] = float(data[prefix + "setpoint"])
        if prefix + "hysteresis" in data:
            ch["hysteresis"] = float(data[prefix + "hysteresis"])
        if prefix + "mode" in data:
            ch["mode"] = "heating" if int(data[prefix + "mode"])==1 else "cooling"
        if prefix + "manual_enable" in data:
            pass  # Frontend gestisce solo flag
    # JSON Update
    config_data["channels"]["ch1"]["setpoint"] = channels["ch1"]["setpoint"]
    config_data["channels"]["ch1"]["hysteresis"] = channels["ch1"]["hysteresis"]
    config_data["channels"]["ch1"]["mode"] = channels["ch1"]["mode"]
    config_data["channels"]["ch1"]["enabled"] = channels["ch1"]["enabled"]

    config_data["channels"]["ch2"]["setpoint"] = channels["ch2"]["setpoint"]
    config_data["channels"]["ch2"]["hysteresis"] = channels["ch2"]["hysteresis"]
    config_data["channels"]["ch2"]["mode"] = channels["ch2"]["mode"]
    config_data["channels"]["ch2"]["enabled"] = channels["ch2"]["enabled"]

    save_config(config_data)
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