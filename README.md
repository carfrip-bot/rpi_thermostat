   _______________________________________________
 /                                                 \
|  Dual Channel Raspberry Pi Thermostat Controller  |
 \_________________________________________________/


OVERVIEW

This project implements a dual-channel temperature control system based on a Raspberry Pi 3 B+.
Each channel (CH1 and CH2) operates independently and can be configured in:

- Heating mode
- Cooling mode
- Automatic control
- Manual override

The system is designed for applications such as:
- Fermentation control
- Cold crash control
- Laboratory temperature regulation

_______________________________________________________________________________________________

FEATURES

- Dual independent temperature channels
- Separate heating/cooling mode per channel
- Configurable setpoint and hysteresis
- Manual override per channel
- Persistent configuration (JSON file retention)
- Web API backend (Flask-based)
- CustomTkinter desktop frontend
- Support for MAX6675 thermocouple modules
- SSR (BERM-SK40DA) output control
- Real-time status updates
- Safe shutdown endpoint for Raspberry Pi

_______________________________________________________________________________________________


HARDWARE REQUIREMENTS

- Raspberry Pi 3B+ (or compatible)
- 2x MAX6675 thermocouple modules
- 2x K-type thermocouples
- BERM-SK40DA SSR or similar (dual channel)
- ULN2003 driver module (for SSR trigger isolation)
- Heating and/or cooling loads
- Properly rated power wiring and protection


⚠️ Warning: This system switches mains voltage. Ensure proper electrical safety, grounding, and protection devices.
