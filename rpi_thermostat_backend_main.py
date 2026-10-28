import json
import logging
import math
import os
import threading
import time
import uuid
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from gpiozero import OutputDevice
import spidev

from firebase_client import FirebaseDatabaseError, FirebaseRealtimeDatabase


APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"

DEFAULT_CONFIG = {
    "revision": 0,
    "updated_at": "1970-01-01T00:00:00+00:00",
    "channels": {
        "ch1": {
            "setpoint": 20.0,
            "hysteresis": 0.5,
            "mode": "heating",
            "enabled": True,
            "schedule": [],
        },
        "ch2": {
            "setpoint": 20.0,
            "hysteresis": 0.5,
            "mode": "heating",
            "enabled": True,
            "schedule": [],
        },
    },
}

CH1_TEMP_OFFSET = -1.0
CH2_TEMP_OFFSET = -1.0
RELAY_ACTIVE_LOW = False
SPI_BUS = 0
CH1_PIN = 17
CH2_PIN = 27
SAMPLES = 50
POLL_INTERVAL = 0.2
STATUS_UPDATE_INTERVAL = 1.0
CONFIG_SYNC_INTERVAL = 2.0
COMMAND_SYNC_INTERVAL = 1.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def normalize_config(data):
    if not isinstance(data, dict):
        raise ValueError("La configurazione deve essere un oggetto JSON")

    channels_data = data.get("channels", {})
    normalized_channels = {}
    for channel_id in ("ch1", "ch2"):
        channel = deepcopy(DEFAULT_CONFIG["channels"][channel_id])
        candidate = channels_data.get(channel_id, {}) if isinstance(channels_data, dict) else {}
        if not isinstance(candidate, dict):
            raise ValueError(f"Configurazione non valida per {channel_id}")
        channel.update(candidate)
        channel["setpoint"] = float(channel["setpoint"])
        channel["hysteresis"] = float(channel["hysteresis"])
        if not math.isfinite(channel["setpoint"]) or not math.isfinite(channel["hysteresis"]):
            raise ValueError(f"Setpoint o isteresi non validi per {channel_id}")
        if channel["mode"] not in ("heating", "cooling"):
            raise ValueError(f"Modalità non valida per {channel_id}")
        if not isinstance(channel["enabled"], bool):
            channel["enabled"] = bool(channel["enabled"])
        if not isinstance(channel["schedule"], list):
            raise ValueError(f"Planning non valido per {channel_id}")
        normalized_channels[channel_id] = channel

    revision = int(data.get("revision", 0))
    if revision < 0:
        raise ValueError("La revisione della configurazione non può essere negativa")

    return {
        "revision": revision,
        "updated_at": str(data.get("updated_at", DEFAULT_CONFIG["updated_at"])),
        "channels": normalized_channels,
    }


def save_config(data):
    """Durably replace the local JSON config before acknowledging cloud changes."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    with temporary_file.open("w", encoding="utf-8") as config_file:
        json.dump(data, config_file, indent=4, ensure_ascii=False)
        config_file.flush()
        os.fsync(config_file.fileno())
    os.replace(temporary_file, CONFIG_FILE)

    # Persist the directory entry too on systems that support directory fsync.
    try:
        directory_fd = os.open(str(CONFIG_FILE.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (AttributeError, OSError):
        pass


def load_config():
    if not CONFIG_FILE.exists():
        config = deepcopy(DEFAULT_CONFIG)
        save_config(config)
        return config

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
            config = normalize_config(json.load(config_file))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        # Do not replace a damaged file with defaults; that could erase the last plan.
        raise RuntimeError(f"Configurazione locale non valida, controllo non avviato: {exc}") from exc

    save_config(config)
    return config


# Hardware is initialized with both outputs OFF. The control loop remains local and
# independent from Firebase connectivity.
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


config_lock = threading.RLock()
config_data = load_config()
channels = {
    "ch1": {
        "temp": None,
        "relay": ch1_relay,
        "spi": spi_ch1,
        "output_on": False,
        **config_data["channels"]["ch1"],
    },
    "ch2": {
        "temp": None,
        "relay": ch2_relay,
        "spi": spi_ch2,
        "output_on": False,
        **config_data["channels"]["ch2"],
    },
}

manual_enabled = False
boot_id = uuid.uuid4().hex
history_ch1 = deque(maxlen=SAMPLES)
history_ch2 = deque(maxlen=SAMPLES)


def control_loop():
    while True:
        try:
            t1_raw = read_max6675(spi_ch1)
            t2_raw = 20.0  # CH2 is intentionally simulated until its hardware is available.

            if t1_raw is not None:
                history_ch1.append(t1_raw)
            if t2_raw is not None:
                history_ch2.append(t2_raw)

            valid_samples_ch1 = [temperature for temperature in history_ch1 if temperature is not None]
            valid_samples_ch2 = [temperature for temperature in history_ch2 if temperature is not None]
            if len(valid_samples_ch1) < SAMPLES:
                time.sleep(POLL_INTERVAL)
                continue

            t1 = (sum(valid_samples_ch1) / len(valid_samples_ch1)) + CH1_TEMP_OFFSET
            t2 = (sum(valid_samples_ch2) / len(valid_samples_ch2)) + CH2_TEMP_OFFSET
            now = datetime.now().replace(second=0, microsecond=0)

            with config_lock:
                channels["ch1"]["temp"] = round(t1, 2)
                channels["ch2"]["temp"] = round(t2, 2)

                for channel in channels.values():
                    if manual_enabled:
                        continue

                    if not channel.get("enabled", True) or channel["temp"] is None:
                        channel["relay"].off()
                        channel["output_on"] = False
                        continue

                    current_setpoint = channel["setpoint"]
                    has_active_schedule = False
                    for entry in channel.get("schedule", []):
                        try:
                            start_dt = datetime.fromisoformat(entry[0]).replace(second=0, microsecond=0)
                            end_dt = datetime.fromisoformat(entry[1]).replace(second=0, microsecond=0)
                            scheduled_setpoint = float(entry[2])
                        except (TypeError, ValueError, IndexError):
                            continue
                        if start_dt <= now < end_dt:
                            current_setpoint = scheduled_setpoint
                            has_active_schedule = True
                            break

                    if has_active_schedule:
                        channel["active_setpoint"] = current_setpoint
                    else:
                        channel.pop("active_setpoint", None)

                    hysteresis = channel["hysteresis"]
                    temperature = channel["temp"]
                    if channel["mode"] == "heating":
                        if temperature < current_setpoint - hysteresis:
                            channel["relay"].on()
                            channel["output_on"] = True
                        elif temperature >= current_setpoint + hysteresis:
                            channel["relay"].off()
                            channel["output_on"] = False
                    elif channel["mode"] == "cooling":
                        if temperature > current_setpoint + hysteresis:
                            channel["relay"].on()
                            channel["output_on"] = True
                        elif temperature <= current_setpoint - hysteresis:
                            channel["relay"].off()
                            channel["output_on"] = False
        except Exception:
            logging.exception("Errore nel ciclo locale di controllo")

        time.sleep(POLL_INTERVAL)


def status_snapshot():
    with config_lock:
        return {
            "manual": manual_enabled,
            "boot_id": boot_id,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "config_revision": config_data["revision"],
            "channels": {
                name.upper(): {
                    "temperature": channel["temp"],
                    "setpoint": channel.get("active_setpoint", channel["setpoint"]),
                    "hysteresis": channel["hysteresis"],
                    "mode": 1 if channel["mode"] == "heating" else 2,
                    "enabled": channel["enabled"],
                    "relay": channel["output_on"],
                    "schedule_enabled": len(channel.get("schedule", [])) > 0,
                }
                for name, channel in channels.items()
            },
        }


def _apply_config(candidate):
    global config_data
    candidate = normalize_config(candidate)
    save_config(candidate)
    with config_lock:
        config_data = candidate
        for channel_id in ("ch1", "ch2"):
            channels[channel_id].update(candidate["channels"][channel_id])
            channels[channel_id].pop("active_setpoint", None)


def _sync_config(database):
    global config_data
    remote_revision = database.get("thermostat/config/revision")
    with config_lock:
        local_config = deepcopy(config_data)

    if remote_revision is None:
        remote_config = database.get("thermostat/config")
        if remote_config is None:
            database.put("thermostat/config", local_config)
            return
        remote_revision = int(remote_config.get("revision", 0))
    else:
        remote_revision = int(remote_revision)
        remote_config = None

    if remote_revision > local_config["revision"]:
        if remote_config is None:
            remote_config = database.get("thermostat/config")
        if remote_config is None:
            return
        candidate = normalize_config(remote_config)
        # Ignore a response that raced with a newer desktop write; the next poll
        # will fetch the current complete revision.
        if candidate["revision"] >= remote_revision and candidate["revision"] > local_config["revision"]:
            _apply_config(candidate)
            logging.info("Configurazione Firebase %s salvata anche in locale", candidate["revision"])
    elif remote_revision < local_config["revision"]:
        database.put("thermostat/config", local_config)
        logging.info("Configurazione locale %s ripubblicata su Firebase", local_config["revision"])


def _set_manual_enabled(enabled):
    global manual_enabled
    with config_lock:
        manual_enabled = bool(enabled)
        if not manual_enabled:
            for channel in channels.values():
                channel["relay"].off()
                channel["output_on"] = False


def _process_command(commands, path, apply_command, last_seen):
    command = commands
    for segment in path.split("/"):
        command = command.get(segment) if isinstance(command, dict) else None
    if not isinstance(command, dict) or command.get("boot_id") != boot_id:
        return
    command_id = command.get("id")
    if not command_id or last_seen.get(path) == command_id:
        return
    apply_command(command)
    last_seen[path] = command_id


def _process_commands(database, last_seen):
    commands = database.get("thermostat/commands") or {}
    _process_command(
        commands,
        "manual_enabled",
        lambda command: _set_manual_enabled(command.get("value", False)),
        last_seen,
    )

    for channel_id in ("ch1", "ch2"):
        def apply_relay(command, channel_id=channel_id):
            with config_lock:
                if not manual_enabled:
                    logging.warning("Ignorato comando relè manuale: modalità manuale disattivata")
                    return
                channel = channels[channel_id]
                if command.get("value", False):
                    channel["relay"].on()
                else:
                    channel["relay"].off()
                channel["output_on"] = bool(command.get("value", False))

        _process_command(commands, f"manual_relay/{channel_id}", apply_relay, last_seen)

    def shutdown(_command):
        with config_lock:
            for channel in channels.values():
                channel["relay"].off()
                channel["output_on"] = False
        logging.warning("Ricevuto comando di spegnimento da Firebase")
        os.system("sudo shutdown now")

    _process_command(commands, "shutdown", shutdown, last_seen)


def firebase_sync_loop():
    database = FirebaseRealtimeDatabase()
    last_seen_commands = {}
    next_config_sync = 0.0
    next_command_sync = 0.0
    next_status_update = 0.0
    last_error = None

    while True:
        now = time.monotonic()
        try:
            if now >= next_config_sync:
                _sync_config(database)
                next_config_sync = now + CONFIG_SYNC_INTERVAL

            if now >= next_command_sync:
                _process_commands(database, last_seen_commands)
                next_command_sync = now + COMMAND_SYNC_INTERVAL

            if now >= next_status_update:
                database.put("thermostat/status", status_snapshot())
                next_status_update = now + STATUS_UPDATE_INTERVAL
                if last_error is not None:
                    logging.info("Connessione a Firebase ripristinata")
                    last_error = None
        except FirebaseDatabaseError as exc:
            message = str(exc)
            if message != last_error:
                logging.warning("Sincronizzazione Firebase non disponibile; il controllo locale continua: %s", message)
                last_error = message
        except Exception:
            logging.exception("Errore durante la sincronizzazione con Firebase")

        time.sleep(0.1)


if __name__ == "__main__":
    threading.Thread(target=control_loop, name="thermostat-control", daemon=True).start()
    threading.Thread(target=firebase_sync_loop, name="firebase-sync", daemon=True).start()
    logging.info("Termostato avviato. Configurazione locale: %s", CONFIG_FILE)
    while True:
        time.sleep(60)
