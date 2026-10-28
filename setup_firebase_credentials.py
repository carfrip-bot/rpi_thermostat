"""Store Firebase credentials in the operating system's secure store.

Windows: Windows Credential Manager via the keyring package.
Linux: an encrypted systemd credential for the Raspberry Pi backend service.
"""

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SERVICE_NAME = "rpi_thermostat"
KEYRING_ACCOUNT = "firebase_config"
DEFAULT_LINUX_CREDENTIAL = Path.home() / ".config/rpi_thermostat/firebase_config.cred"


def read_config(args):
    if args.from_json:
        with Path(args.from_json).expanduser().open("r", encoding="utf-8") as source:
            config = json.load(source)
    else:
        config = {
            "api_key": input("Firebase Web API key: ").strip(),
            "database_url": input("Realtime Database URL: ").strip(),
            "email": input("Email utente Firebase: ").strip(),
            "password": getpass.getpass("Password utente Firebase: "),
            "user_uid": input("UID utente Firebase: ").strip(),
            "timeout_seconds": 5.0,
        }

    required = ("api_key", "database_url", "email", "password", "user_uid")
    missing = [field for field in required if not config.get(field)]
    if missing:
        raise ValueError("Campi Firebase mancanti: " + ", ".join(missing))
    config["timeout_seconds"] = float(config.get("timeout_seconds", 5.0))
    return config


def store_windows(config):
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Installa il pacchetto Windows: python -m pip install keyring") from exc

    keyring.set_password(SERVICE_NAME, KEYRING_ACCOUNT, json.dumps(config))
    print("Credenziali salvate in Windows Credential Manager.")


def store_linux(config, output_path):
    systemd_creds = shutil.which("systemd-creds")
    if not systemd_creds:
        raise RuntimeError("systemd-creds non è disponibile su questo Raspberry Pi")

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(output_path.parent, 0o700)
    temporary_path = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".firebase-plaintext-", dir=str(output_path.parent)
        )
        temporary_path = Path(temporary_name)
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(config, temporary_file)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        subprocess.run(
            [
                systemd_creds,
                "encrypt",
                "--name=firebase_config",
                str(temporary_path),
                str(output_path),
            ],
            check=True,
        )
        os.chmod(output_path, 0o600)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    print(f"Credenziale cifrata creata: {output_path}")
    print("Aggiungi LoadCredentialEncrypted=firebase_config:" + str(output_path) + " al servizio systemd del backend.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", help="Importa una configurazione esistente; il file non viene eliminato automaticamente")
    parser.add_argument("--delete-source", action="store_true", help="Elimina il JSON sorgente dopo aver salvato la credenziale")
    parser.add_argument("--output", type=Path, default=DEFAULT_LINUX_CREDENTIAL, help="Percorso credenziale cifrata su Linux")
    args = parser.parse_args()

    if args.delete_source and not args.from_json:
        parser.error("--delete-source richiede --from-json")

    try:
        config = read_config(args)
        if os.name == "nt":
            store_windows(config)
        elif sys.platform.startswith("linux"):
            store_linux(config, args.output)
        else:
            raise RuntimeError("Sistema operativo non supportato")

        if args.delete_source:
            Path(args.from_json).expanduser().unlink()
            print("JSON sorgente eliminato (la cancellazione non garantisce la rimozione da backup o memoria flash).")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
