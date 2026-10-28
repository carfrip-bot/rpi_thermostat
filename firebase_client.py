"""Small authenticated Firebase Realtime Database REST client.

The requests session is kept open so repeated polling can reuse its HTTPS
connection instead of paying for a new TLS handshake on every request.
"""

import json
import os
import threading
import time
from pathlib import Path

import requests


class FirebaseDatabaseError(RuntimeError):
    """Raised when Firebase configuration, authentication, or I/O fails."""


class FirebaseRealtimeDatabase:
    def __init__(self):
        self._config = None
        self._session = requests.Session()
        self._id_token = None
        self._refresh_token = None
        self._token_expires_at = 0.0
        self._lock = threading.RLock()

    def _load_config(self):
        if self._config is not None:
            return self._config

        raw_config = None
        credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if credentials_directory:
            credential_file = Path(credentials_directory) / "firebase_config"
            try:
                raw_config = credential_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FirebaseDatabaseError(f"Credenziale systemd non leggibile: {exc}") from exc

        if raw_config is None and os.name == "nt":
            try:
                import keyring

                raw_config = keyring.get_password("rpi_thermostat", "firebase_config")
            except Exception as exc:
                raise FirebaseDatabaseError(
                    "Impossibile leggere Windows Credential Manager; installa keyring e configura le credenziali"
                ) from exc

        if raw_config is None:
            if os.name == "nt":
                hint = "Esegui setup_firebase_credentials.py per salvarle in Windows Credential Manager."
            else:
                hint = "Avvia il backend come servizio systemd con LoadCredentialEncrypted=firebase_config:..."
            raise FirebaseDatabaseError(f"Credenziali Firebase non configurate. {hint}")

        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError as exc:
            raise FirebaseDatabaseError(f"Credenziale Firebase non è un JSON valido: {exc}") from exc
        if not isinstance(config, dict):
            raise FirebaseDatabaseError("La credenziale Firebase deve contenere un oggetto JSON")

        required = ("api_key", "database_url", "email", "password", "user_uid")
        missing = [key for key in required if not config.get(key)]
        if missing:
            raise FirebaseDatabaseError(
                "Configurazione Firebase incompleta; campi mancanti: " + ", ".join(missing)
            )

        database_url = str(config["database_url"]).rstrip("/")
        if not database_url.startswith("https://"):
            raise FirebaseDatabaseError("database_url deve usare HTTPS")

        self._config = {
            "api_key": str(config["api_key"]),
            "database_url": database_url,
            "email": str(config["email"]),
            "password": str(config["password"]),
            "user_uid": str(config["user_uid"]),
            "timeout_seconds": float(config.get("timeout_seconds", 5.0)),
        }
        return self._config

    def _authenticate(self):
        config = self._load_config()
        url = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        try:
            response = self._session.post(
                url,
                params={"key": config["api_key"]},
                json={
                    "email": config["email"],
                    "password": config["password"],
                    "returnSecureToken": True,
                },
                timeout=config["timeout_seconds"],
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise FirebaseDatabaseError(
                f"Autenticazione Firebase non riuscita ({self._safe_error(exc)})"
            ) from exc

        self._id_token = data["idToken"]
        if data.get("localId") != config["user_uid"]:
            self._id_token = None
            raise FirebaseDatabaseError("L'utente Firebase configurato non corrisponde allo UID atteso")
        self._refresh_token = data["refreshToken"]
        self._token_expires_at = time.monotonic() + int(data.get("expiresIn", "3600"))

    def _refresh_auth(self):
        config = self._load_config()
        if not self._refresh_token:
            self._authenticate()
            return

        url = "https://securetoken.googleapis.com/v1/token"
        try:
            response = self._session.post(
                url,
                params={"key": config["api_key"]},
                data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
                timeout=config["timeout_seconds"],
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            self._id_token = None
            raise FirebaseDatabaseError(
                f"Rinnovo autenticazione Firebase non riuscito ({self._safe_error(exc)})"
            ) from exc

        self._id_token = data["id_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._token_expires_at = time.monotonic() + int(data.get("expires_in", "3600"))

    def _ensure_token(self):
        if self._id_token is None:
            self._authenticate()
        elif time.monotonic() >= self._token_expires_at - 60:
            self._refresh_auth()

    @staticmethod
    def _safe_error(exc):
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                message = response.json().get("error", {}).get("message")
            except (ValueError, AttributeError):
                message = None
            if message:
                return f"HTTP {response.status_code}: {message}"
            return f"HTTP {response.status_code}"
        return type(exc).__name__

    def get(self, path):
        return self._request("GET", path)

    def put(self, path, value):
        self._request("PUT", path, value=value)

    def delete(self, path):
        self._request("DELETE", path)

    def _request(self, method, path, value=None):
        config = self._load_config()
        clean_path = "/".join(part for part in str(path).strip("/").split("/") if part)
        url = f"{config['database_url']}/{clean_path}.json"

        with self._lock:
            self._ensure_token()
            for attempt in range(2):
                try:
                    params = {"auth": self._id_token}
                    if method == "PUT":
                        # Avoid downloading a copy of the object just written.
                        params["print"] = "silent"
                        response = self._session.put(
                            url,
                            params=params,
                            json=value,
                            timeout=config["timeout_seconds"],
                        )
                    elif method == "DELETE":
                        response = self._session.delete(
                            url,
                            params=params,
                            timeout=config["timeout_seconds"],
                        )
                    else:
                        response = self._session.get(
                            url,
                            params=params,
                            timeout=config["timeout_seconds"],
                        )

                    if response.status_code in (401, 403) and attempt == 0:
                        self._refresh_auth()
                        continue
                    response.raise_for_status()
                    if method == "GET":
                        return response.json()
                    return None
                except requests.RequestException as exc:
                    raise FirebaseDatabaseError(
                        f"Richiesta Firebase non riuscita ({self._safe_error(exc)})"
                    ) from exc
                except ValueError as exc:
                    raise FirebaseDatabaseError("Firebase ha restituito una risposta non JSON") from exc

        raise FirebaseDatabaseError("Richiesta Firebase non riuscita dopo il rinnovo del token")
