#!/usr/bin/env python3

import time
import os
import json
import socket

from configparser import RawConfigParser
from pymodbus.client.sync import ModbusSerialClient as ModbusClient
from growatt import Growatt

# --- Optional MQTT (paho-mqtt) ---
try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None


def mqtt_setup(cfg):
    """Create and connect a single MQTT client (or return None if disabled/missing)."""
    if not cfg.getboolean('mqtt', 'enable', fallback=False):
        return None
    if mqtt is None:
        print("MQTT enabled but paho-mqtt not installed; continuing without MQTT.")
        return None

    host = cfg.get('mqtt', 'host', fallback='127.0.0.1')
    port = cfg.getint('mqtt', 'port', fallback=1883)
    username = cfg.get('mqtt', 'username', fallback=None)
    password = cfg.get('mqtt', 'password', fallback=None)
    base = cfg.get('mqtt', 'base_topic', fallback='solar/inverter').rstrip('/')

    client_id = f"solarmon-{socket.gethostname()}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
    if username:
        client.username_pw_set(username, password or None)

    # LWT / availability
    avail_topic = f"{base}/availability"
    client.will_set(avail_topic, payload="offline", qos=0, retain=True)

    client.connect(host, port, keepalive=30)
    client.loop_start()

    # Mark online
    client.publish(avail_topic, "online", qos=0, retain=True)
    return client


# ---------------------------------------------------------------------------
# Sensor definitions: topic_suffix -> (name, unit, device_class, state_class)
# ---------------------------------------------------------------------------
SENSOR_DEFS = {
    "power":              ("Power",              "W",   "power",       "measurement"),
    "pv_power":           ("PV Power",           "W",   "power",       "measurement"),
    "pv1_voltage":        ("PV1 Voltage",        "V",   "voltage",     "measurement"),
    "pv1_current":        ("PV1 Current",        "A",   "current",     "measurement"),
    "ac_voltage":         ("AC Voltage",         "V",   "voltage",     "measurement"),
    "ac_current":         ("AC Current",         "A",   "current",     "measurement"),
    "grid_frequency":     ("Grid Frequency",     "Hz",  None,          "measurement"),
    "inverter_temp":      ("Inverter Temperature","°C", "temperature", "measurement"),
    "energy_today":       ("Energy Today",       "kWh", "energy",      "total"),
    "energy_total":       ("Energy Total",       "kWh", "energy",      "total_increasing"),
    "inverter_status":    ("Inverter Status",    None,  None,          None),
    "inverter_status_code":("Inverter Status Code",None, None,         None),
}

# Modbus field -> (topic_suffix, formatter)
FIELD_MAP = {
    "Pac":        ("power",              lambda v: f"{float(v):.0f}"),
    "Ppv":        ("pv_power",           lambda v: f"{float(v):.0f}"),
    "Vpv1":       ("pv1_voltage",        lambda v: f"{float(v):.1f}"),
    "PV1Curr":    ("pv1_current",        lambda v: f"{float(v):.2f}"),
    "Vac1":       ("ac_voltage",         lambda v: f"{float(v):.1f}"),
    "Iac1":       ("ac_current",         lambda v: f"{float(v):.2f}"),
    "Fac":        ("grid_frequency",     lambda v: f"{float(v):.2f}"),
    "Temp":       ("inverter_temp",      lambda v: f"{float(v):.1f}"),
    "EnergyToday":("energy_today",       lambda v: f"{float(v):.3f}"),
    "EnergyTotal":("energy_total",       lambda v: f"{float(v):.3f}"),
    "Status":     ("inverter_status",    lambda v: str(v)),
    "StatusCode": ("inverter_status_code",lambda v: str(int(v))),
}


def mqtt_publish_discovery(client, cfg):
    """Publish HA MQTT Discovery for all sensors."""
    if not client or not cfg.getboolean('mqtt', 'ha_discovery', fallback=True):
        return

    base = cfg.get('mqtt', 'base_topic', fallback='solar/inverter').rstrip('/')
    prefix = cfg.get('mqtt', 'ha_prefix', fallback='homeassistant').rstrip('/')
    device_id = cfg.get('mqtt', 'device_id', fallback='solar_inverter')
    device_name = cfg.get('mqtt', 'device_name', fallback='Solar Inverter')
    avail_topic = f"{base}/availability"

    device = {
        "identifiers": [device_id],
        "manufacturer": "Growatt",
        "model": "1000S",
        "name": device_name,
    }

    for suffix, (name, uom, dev_class, state_class) in SENSOR_DEFS.items():
        uid = f"{device_id}_{suffix}"
        cfg_topic = f"{prefix}/sensor/{uid}/config"
        state_topic = f"{base}/{suffix}"

        payload = {
            "name": name,
            "unique_id": uid,
            "default_entity_id": f"sensor.{device_id}_{suffix}",
            "state_topic": state_topic,
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        if uom:         payload["unit_of_measurement"] = uom
        if dev_class:   payload["device_class"] = dev_class
        if state_class: payload["state_class"] = state_class

        client.publish(cfg_topic, json.dumps(payload), qos=0, retain=True)


def mqtt_publish_values(client, cfg, info):
    """Publish all sensor values from a Growatt read."""
    if not client or not info:
        return

    base = cfg.get('mqtt', 'base_topic', fallback='solar/inverter').rstrip('/')
    retain = cfg.getboolean('mqtt', 'retain', fallback=True)

    for field, (suffix, formatter) in FIELD_MAP.items():
        val = info.get(field)
        if val is None:
            continue
        try:
            payload = formatter(val)
            client.publish(f"{base}/{suffix}", payload, qos=0, retain=retain)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
settings = RawConfigParser()
settings.read(os.path.dirname(os.path.realpath(__file__)) + '/solarmon.cfg')

interval = settings.getint('query', 'interval', fallback=1)
offline_interval = settings.getint('query', 'offline_interval', fallback=60)
error_interval = settings.getint('query', 'error_interval', fallback=60)

# Serial connection
print('Setup Serial Connection... ', end='')
port = settings.get('solarmon', 'port', fallback='/dev/ttyUSB0')
client = ModbusClient(method='rtu', port=port, baudrate=9600, stopbits=1, parity='N', bytesize=8, timeout=1)
client.connect()
print('Done!')

# MQTT
mqtt_client = mqtt_setup(settings)

print('Loading inverters... ')
inverters = []
for section in settings.sections():
    if not section.startswith('inverters.'):
        continue

    name = section[10:]
    unit = int(settings.get(section, 'unit'))
    measurement = settings.get(section, 'measurement')
    growatt = Growatt(client, name, unit)
    growatt.print_info()
    inverters.append({
        'name': name,
        'error_sleep': 0,
        'growatt': growatt,
        'measurement': measurement
    })

# Publish HA discovery once at startup
if mqtt_client:
    mqtt_publish_discovery(mqtt_client, settings)

print('Done!')

while True:
    online = False
    for inverter in inverters:
        if inverter['error_sleep'] > 0:
            inverter['error_sleep'] -= interval
            continue

        growatt = inverter['growatt']
        try:
            info = growatt.read()

            if info is None:
                continue

            online = True

            if mqtt_client:
                mqtt_publish_values(mqtt_client, settings, info)

        except Exception as err:
            print(growatt.name)
            print(err)
            inverter['error_sleep'] = error_interval

    if online:
        time.sleep(interval)
    else:
        time.sleep(offline_interval)