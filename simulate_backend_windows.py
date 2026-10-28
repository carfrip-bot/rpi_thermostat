"""Run a hardware-free Raspberry Pi backend simulator on Windows.

Publishes the same thermostat/status shape as the Raspberry Pi backend, mirrors
configuration revisions for frontend acknowledgements, and processes manual
commands. Shutdown commands are logged and ignored to keep the PC safe.
"""

import argparse
import logging
import math
import time
import uuid
from datetime import datetime, timezone

from firebase_client import FirebaseDatabaseError, FirebaseRealtimeDatabase


DEFAULT_CONFIG = {
    "revision": 0,
    "updated_at": "1970-01-01T00:00:00+00:00",
    "channels": {
        "ch1": {"setpoint": 20.0, "hysteresis": 0.5, "mode": "heating", "enabled": True, "schedule": []},
        "ch2": {"setpoint": 20.0, "hysteresis": 0.5, "mode": "heating", "enabled": True, "schedule": []},
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1.0, help="Secondi tra gli aggiornamenti (default: 1)")
    parser.add_argument("--ch1-temp", type=float, default=19.0, help="Temperatura simulata CH1")
    parser.add_argument("--ch2-temp", type=float, default=21.0, help="Temperatura simulata CH2")
    args = parser.parse_args()
    if args.interval < 0.5:
        parser.error("--interval deve essere almeno 0.5 secondi")
    return args


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database = FirebaseRealtimeDatabase()
    boot_id = uuid.uuid4().hex
    manual_enabled = False
    last_seen_commands = {}
    relay_states = {"ch1": False, "ch2": False}
    config = None
    last_config_revision = None
    next_config_poll = 0.0
    cycle = 0

    logging.info("Simulatore backend avviato (boot_id=%s). Ctrl+C per fermare.", boot_id)
    logging.info("Temperature simulate: CH1=%.1f °C, CH2=%.1f °C", args.ch1_temp, args.ch2_temp)

    while True:
        try:
            now = time.monotonic()
            if config is None or now >= next_config_poll:
                remote_revision = database.get("thermostat/config/revision")
                observed_revision = int(remote_revision) if remote_revision is not None else 0
                if config is None or observed_revision != last_config_revision:
                    remote_config = database.get("thermostat/config")
                    if not isinstance(remote_config, dict):
                        config = DEFAULT_CONFIG
                        database.put("thermostat/config", config)
                        logging.info("Configurazione iniziale creata in thermostat/config")
                    else:
                        config = remote_config
                    last_config_revision = config.get("revision", 0)
                next_config_poll = now + 2.0

            commands = database.get("thermostat/commands") or {}
            relay_commands = commands.get("manual_relay", {})
            if not isinstance(relay_commands, dict):
                relay_commands = {}
            command_items = [("manual_enabled", commands.get("manual_enabled"))]
            command_items.extend(
                (f"manual_relay/ch{number}", relay_commands.get(f"ch{number}"))
                for number in (1, 2)
            )
            command_items.append(("shutdown", commands.get("shutdown")))

            for command_path, command in command_items:
                if not isinstance(command, dict) or command.get("boot_id") != boot_id:
                    continue
                command_id = command.get("id")
                if not command_id or last_seen_commands.get(command_path) == command_id:
                    continue
                last_seen_commands[command_path] = command_id

                if command_path == "manual_enabled":
                    manual_enabled = bool(command.get("value", False))
                    logging.info("Modalità manuale: %s", "ON" if manual_enabled else "OFF")
                    if not manual_enabled:
                        relay_states = {"ch1": False, "ch2": False}
                elif command_path.startswith("manual_relay/"):
                    channel_id = command_path.rsplit("/", 1)[1]
                    if manual_enabled:
                        relay_states[channel_id] = bool(command.get("value", False))
                        logging.info("Relè simulato %s: %s", channel_id.upper(), "ON" if relay_states[channel_id] else "OFF")
                    else:
                        logging.info("Comando relè ignorato: modalità manuale disattivata")
                else:
                    logging.info("Comando di spegnimento ricevuto; ignorato dal simulatore Windows")

            elapsed = cycle * args.interval
            temperatures = {
                "ch1": args.ch1_temp + 0.15 * math.sin(elapsed / 20.0),
                "ch2": args.ch2_temp + 0.15 * math.sin(elapsed / 23.0),
            }
            channels_status = {}
            for channel_id in ("ch1", "ch2"):
                channel = config.get("channels", {}).get(channel_id, {})
                setpoint = float(channel.get("setpoint", 20.0))
                hysteresis = float(channel.get("hysteresis", 0.5))
                mode = channel.get("mode", "heating")
                if not manual_enabled:
                    if not channel.get("enabled", True):
                        relay_states[channel_id] = False
                    elif mode == "heating":
                        if temperatures[channel_id] < setpoint - hysteresis:
                            relay_states[channel_id] = True
                        elif temperatures[channel_id] >= setpoint + hysteresis:
                            relay_states[channel_id] = False
                    else:
                        if temperatures[channel_id] > setpoint + hysteresis:
                            relay_states[channel_id] = True
                        elif temperatures[channel_id] <= setpoint - hysteresis:
                            relay_states[channel_id] = False

                channels_status[channel_id.upper()] = {
                    "temperature": round(temperatures[channel_id], 2),
                    "setpoint": setpoint,
                    "hysteresis": hysteresis,
                    "mode": 1 if mode == "heating" else 2,
                    "enabled": bool(channel.get("enabled", True)),
                    "relay": relay_states[channel_id],
                    "schedule_enabled": bool(channel.get("schedule", [])),
                }

            status = {
                "manual": manual_enabled,
                "boot_id": boot_id,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "config_revision": int(config.get("revision", 0)),
                "channels": channels_status,
                "simulated": True,
            }
            database.put("thermostat/status", status)
            if cycle == 0 or cycle % max(1, round(10 / args.interval)) == 0:
                logging.info(
                    "Stato pubblicato (rev=%s, CH1=%.1f °C, CH2=%.1f °C)",
                    status["config_revision"],
                    temperatures["ch1"],
                    temperatures["ch2"],
                )
            cycle += 1
            time.sleep(args.interval)
        except FirebaseDatabaseError as exc:
            logging.error("Firebase non raggiungibile: %s", exc)
            time.sleep(max(args.interval, 2.0))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSimulatore fermato. thermostat/status smetterà di aggiornarsi e il frontend lo vedrà offline.")
