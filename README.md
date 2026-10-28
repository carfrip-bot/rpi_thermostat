_______________________________________________________________________________________________

# Dual Channel Raspberry Pi Thermostat Controller
_______________________________________________________________________________________________


## OVERVIEW

This project implements a dual-channel temperature control system based on a Raspberry Pi 3+.
Each channel (CH1 and CH2) operates independently and can be configured in:

-   Heating mode
-   Cooling mode
-   Automatic control
-   Manual override

The system is suitable for:

-   Fermentation control
-   Brewing systems
-   Process temperature regulation
-   Laboratory applications

_______________________________________________________________________________________________

## FEATURES

-   Dual independent temperature channels
-   Configurable setpoint and hysteresis
-   Manual override per channel
-   Persistent configuration storage (JSON)
-   Firebase Realtime Database communication
-   Responsive browser frontend for desktop and mobile
-   MAX6675 thermocouple support
-   SSR relay control
-   Real-time monitoring
-	Temperature scheduling
-   Remote shutdown command
-   Events Logger

_______________________________________________________________________________________________


## HARDWARE REQUIREMENTS

-   Raspberry Pi 3B+ (or compatible)
-   2x MAX6675 thermocouple modules
-   2x K-type thermocouples
-   2x SSR relays (e.g., BERM-SK40DA)
-   Properly rated wiring and protection devices

⚠️ Warning: This system may switch mains voltage. Ensure proper
electrical safety and protection.

_______________________________________________________________________________________________


## SOFTWARE REQUIREMENTS

Backend (Raspberry Pi)

-   Python 3
-   requests
-   gpiozero
-   spidev

Install dependencies:

    pip install requests gpiozero spidev

Legacy Python frontend (optional)

-   Python 3
-   customtkinter
-   requests
-   keyring
-   CTkMessagebox
-	tkcalendar

Install dependencies:

    pip install customtkinter requests keyring CTkMessagebox tkcalendar

- Properly rated power wiring and protection

_______________________________________________________________________________________________

## FIREBASE SETUP AND DATA FLOW

Firebase Realtime Database is used for signals exhange. The Raspberry Pi
performs all sensor reads, scheduling, and relay control locally for safety reasons.
The browser frontend and Raspberry Pi exchange configuration, commands, and status
through the `thermostat` node in Firebase.

1. Create a Firebase project and a Realtime Database.
2. Enable Email/Password under Firebase Authentication and create a dedicated
   user for this thermostat.
3. Set Realtime Database rules so only authenticated users can access the
   thermostat node. For a project containing only this thermostat, the basic
   rules are:

       {
         "rules": {
           "thermostat": {
             ".read": "auth != null && auth.uid === 'THERMOSTAT_USER_UID'",
             ".write": "auth != null && auth.uid === 'THERMOSTAT_USER_UID'"
           }
         }
       }

4. Replace `THERMOSTAT_USER_UID` in the rules with that UID. The Firebase Web
   API key identifies the project and is not an authentication secret; the
   account password and restrictive database rules protect the data.
5. On the Raspberry Pi, run the setup script with Python 3 to create an
   encrypted systemd credential from an existing private JSON file:

       python3 setup_firebase_credentials.py --from-json firebase_config.json --delete-source

   The Pi setup requires `systemd-creds` and systemd 250 or later. Edit
   `thermostat.service.example` for the Pi's actual username and project path,
   install it as `/etc/systemd/system/thermostat.service`, then run
   `sudo systemctl daemon-reload`, `sudo systemctl enable --now thermostat`.
   The backend reads the decrypted credential from systemd's temporary
   read-only credential directory when the service starts. The password is
   encrypted on disk; the JSON is only needed temporarily during import.
6. Run the Raspberry Pi backend as the configured systemd service so it can
   access its encrypted credential. The legacy Python frontend can still use
   Windows Credential Manager, configured with `python setup_firebase_credentials.py`.

### Web frontend

The responsive browser frontend is in `web/`. It connects directly to Firebase
Realtime Database and shares the same Python desktop UI functionality; it can be
integrated into any web app.
Open a terminal in the project folder and serve the static page locally:

    python -m http.server 8080 --bind 127.0.0.1 --directory web

Open `http://localhost:8080` in a browser. On first login, enter the Firebase
Web API key, database URL, and dedicated Email/Password account. The API key,
database URL, and optional UID are saved in that browser; the password and
authentication tokens stay in memory for the current tab and are cleared when
you sign out or close it. Use HTTPS hosting (for example Firebase Hosting) to
access the page securely from a phone or another network. Do not publish the
page on an untrusted host: Realtime Database rules must restrict access to the
dedicated thermostat UID.

To test the database and web frontend without the Raspberry Pi, start the
simulator in one terminal:

    python simulate_backend_windows.py

Start the static web server in a second terminal with the command above. The
simulator publishes fake temperatures every second, syncs configuration
revisions, and processes manual relay commands as simulated state only. It
ignores shutdown commands, so it will not shut down the PC. Stop it with
Ctrl+C; the page should then mark the thermostat offline after the 10-second
status timeout.

The Firebase Web API key identifies the project; Firebase documents that API
keys are not used to authorize database access. The dedicated account and
UID-restricted Realtime Database rules protect its data. Do not use an
unrestricted database or a personal account that has access to other Firebase
projects.

### Local recovery and offline operation

The Raspberry Pi stores the complete channel configuration and planning in
`config.json` next to the backend script. Each update is written to a temporary
file, flushed to disk, and atomically renamed before the backend applies it.
At startup, the backend loads this file before starting the control loop. If
Firebase or the network is unavailable, control continues from the last local
configuration and the synchronization thread retries in the background. When
the network returns, a newer cloud revision is first saved locally and then
applied; if the cloud has an older revision, the local revision is uploaded.

Setpoints, modes, hysteresis, enable state, and schedules are synced as one
versioned configuration. Manual relay commands and shutdown requests are
temporary commands tied to the current Raspberry boot, so stale commands are
not replayed after a restart.

### Approximate Firebase free-tier traffic

The desktop reads the status once per second.
The Raspberry Pi publishes a heartbeat/status once per second, checks
manual commands once per second, and checks the small configuration revision
every two seconds. The current status JSON is about 383 bytes: at 2,592,000
reads in a 30-day month, that is about 1.0 GB of status payload alone. The
command reads add roughly 1.3 GB of payload; the remaining reads, write
responses, and protocol overhead bring the planning estimate to about
**4–5 GB per 30-day month** (40–50% of Realtime Database's 10 GB/month no-cost
download allowance). This assumes one desktop client and the persistent HTTPS
connections used by the app. Actual billing depends on connection reuse and
protocol overhead, so check the Firebase console's Realtime Database Downloads
graph after running the system. If measured usage approaches 7.5–8 GB/month,
increase the status intervals in the backend and desktop configuration.

_______________________________________________________________________________________________


_______________________________________________________________________________________________

## SAFETY RECOMMENDATIONS

-   Use proper fuses or circuit breakers.
-   Ensure SSR heat dissipation.
-   Use appropriately rated wiring.
-   Never work on live circuits.

_______________________________________________________________________________________________

## LICENSE

Provided for educational and experimental purposes.
Use at your own risk.

