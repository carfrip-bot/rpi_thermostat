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
-   Flask-based REST API backend
-   CustomTkinter desktop frontend
-   MAX6675 thermocouple support
-   SSR relay control
-   Real-time monitoring
-   Safe shutdown endpoint

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
-   Flask
-   spidev
-   RPi.GPIO

Install dependencies:

    pip install flask spidev RPi.GPIO

Frontend (Desktop)

-   Python 3
-   customtkinter
-   requests
-   CTkMessagebox

Install dependencies:

    pip install customtkinter requests CTkMessagebox

- Properly rated power wiring and protection


_______________________________________________________________________________________________

## SAFETY RECOMMENDATIONS

-   Use proper fuses or circuit breakers.
-   Ensure SSR heat dissipation.
-   Use appropriately rated wiring.
-   Never work on live circuits.

_______________________________________________________________________________________________

## LICENSE

Provided for educational and experimental purposes. Use at your own
risk.

