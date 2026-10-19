"""Console protocols, without any Home Assistant import.

Each module talks to one family of consoles and can be tested on its own:

- ``ddp``: PlayStation 5 discovery, status and wake-up (UDP 9302).
- ``remoteplay``: PlayStation 5 Remote Play control channel (pairing, standby).
- ``webman``: PlayStation 3 running webMAN MOD (HTTP).
- ``switch_assistant``: Nintendo Switch running Switch Assistant (MQTT topics).
"""
