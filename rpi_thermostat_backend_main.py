import time
import threading
import json
import os
from flask import Flask, jsonify, request
from gpiozero import OutputDevice
import spidev

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
            "enabled": True
        },
        "ch2": {
            "setpoint": 20.0,
            "hysteresis": 0.5,
            "mode": "heating",
            "enabled": True
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
        # file corrotto
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

manual_enabled = False
POLL_INTERVAL = 1.0


# ==============================
# CONTROL LOOP
# ==============================

def control_loop():
    while True:
        try:
            for name, ch in channels.items():

                ch["temp"] = read_max6675(ch["spi"])

                if manual_enabled:
                    continue

                if not ch["enabled"] or ch["temp"] is None:
                    ch["relay"].off()
                    ch["output_on"] = False
                    continue

                sp = ch["setpoint"]
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
            name: {
                "temp": ch["temp"],
                "setpoint": ch["setpoint"],
                "hysteresis": ch["hysteresis"],
                "mode": ch["mode"],
                "enabled": ch["enabled"],
                "output_on": ch["output_on"]
            }
            for name, ch in channels.items()
        }
    })


@app.post("/config/<channel>")
def config_channel(channel):
    if channel not in channels:
        return jsonify({"error": "invalid channel"}), 404

    data = request.json or {}
    ch = channels[channel]

    if "setpoint" in data:
        ch["setpoint"] = float(data["setpoint"])

    if "hysteresis" in data:
        ch["hysteresis"] = float(data["hysteresis"])

    if "mode" in data:
        if data["mode"] in ["heating", "cooling"]:
            ch["mode"] = data["mode"]

    if "enabled" in data:
        ch["enabled"] = bool(data["enabled"])

    # aggiorno file persistente
    config_data["channels"][channel] = {
        "setpoint": ch["setpoint"],
        "hysteresis": ch["hysteresis"],
        "mode": ch["mode"],
        "enabled": ch["enabled"]
    }

    save_config(config_data)

    return jsonify({"ok": True})


@app.post("/manual_mode")
def manual_mode():
    global manual_enabled
    data = request.json or {}
    manual_enabled = bool(data.get("enabled", False))

    if not manual_enabled:
        for ch in channels.values():
            ch["relay"].off()
            ch["output_on"] = False

    return jsonify({"ok": True})


@app.post("/manual/<channel>")
def manual_control(channel):
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


# ==============================
# AVVIO
# ==============================

if __name__ == "__main__":
    thread = threading.Thread(target=control_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5000)