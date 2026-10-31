Solarmon
----
A simple Python Script for reading Growatt PV Inverter Modbus RS485 RTU Protocol and publishing telemetry via MQTT

[Protocol Documentation](docs/README.md)

How to use
----
- Some hardware running a Linux based OS with Python 3.9+ (eg. Raspberry Pi)
- Connect your Linux based OS to the RS485 port on the inverter via a RS485 to USB cable
- Copy `solarmon.cfg.example` to `solarmon.cfg` and modify the config values to your setup as needed
- Run `pip install -r requirements.txt`
- Run `python3 solarmon.py` in a screen (or you could setup a service if that is your preference)

MQTT / Home Assistant
----
Telemetry is published to MQTT only; configure the `[mqtt]` section in `solarmon.cfg`:

| Key | Default | Description |
|---|---|---|
| `enable` | `false` | Enable MQTT publishing |
| `host` / `port` | `127.0.0.1` / `1883` | Broker address |
| `username` / `password` | – | Broker credentials (optional) |
| `base_topic` | `solar/inverter` | State topics are `<base_topic>/<sensor>`; availability on `<base_topic>/availability` |
| `retain` | `true` | Retain state messages |
| `ha_discovery` | `true` | Publish Home Assistant MQTT discovery configs |
| `ha_prefix` | `homeassistant` | HA discovery prefix |
| `device_id` / `device_name` | `solar_inverter` / `Solar Inverter` | HA device identity |


Reading from Multiple Units
----
To read from multiple units add a new section to the `solarmon.cfg` config with the unit's id.
```ini
[inverters.<name>]
unit = <id>
```
Example:
```ini
[inverters.unit2]
unit = 2
```

Use your MQTT broker and client (for example Home Assistant MQTT discovery) to view inverter telemetry.

Systemd Service
---
- Copy `solarmon.service` to `/etc/systemd/system`
- Modify the `WorkingDirectory` and `User` to suit your setup.
- Run `systemctl start solarmon` to start the service.
- Run `systemctl status solarmon` and ensure that the service is running correctly.
- Run `systemctl enable solarmon` to make the service automatically start when the system does.
