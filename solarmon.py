#!/usr/bin/env python3

import time
import os
import json
import socket

from configparser import RawConfigParser
from pymodbus.client.sync import ModbusSerialClient as ModbusClient
#from influxdb import InfluxDBClient
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
    base = cfg.get('mqtt', 'base_topic', fallback='growatt/solar').rstrip('/')

    client_id = f"solarmon-{socket.gethostname()}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    if username:
        client.username_pw_set(username, password or None)

    # LWT / availability (shared for all sensors)
    avail_topic = f"{base}/availability"
    client.will_set(avail_topic, payload="offline", qos=0, retain=True)

    client.connect(host, port, keepalive=30)
    client.loop_start()

    # Mark online
    client.publish(avail_topic, "online", qos=0, retain=True)
    return client


def mqtt_publish_discovery(client, cfg, inverter_name):
    """Publish HA MQTT Discovery for one inverter (Power + Total Energy)."""
    if not client or not cfg.getboolean('mqtt', 'ha_discovery', fallback=True):
        return
    base = cfg.get('mqtt', 'base_topic', fallback='growatt/solar').rstrip('/')
    prefix = cfg.get('mqtt', 'ha_prefix', fallback='homeassistant').rstrip('/')
    device_root = cfg.get('mqtt', 'device_id', fallback='growatt_1000s')
    device_name_root = cfg.get('mqtt', 'device_name', fallback='Growatt Inverter')
    avail_topic = f"{base}/availability"

    # Use a per-inverter device so names/entities stay tidy if you add more later
    device_id = f"{device_root}_{inverter_name}"
    device = {
        "identifiers": [device_id],
        "manufacturer": "Growatt",
        "model": "1000S",
        "name": f"{device_name_root} ({inverter_name})",
    }

    # Topics for this inverter
    power_state = f"{base}/{inverter_name}/power_w"
    energy_state = f"{base}/{inverter_name}/energy_kwh"

    # Power sensor
    power_uid = f"{device_id}_power"
    power_cfg_topic = f"{prefix}/sensor/{power_uid}/config"
    power_cfg = {
        "name": f"{inverter_name} Current solar output",
        "unique_id": power_uid,
	"default_entity_id": "sensor.solar_power",
        "state_topic": power_state,
        "unit_of_measurement": "W",
        "device_class": "power",
        "state_class": "measurement",
        "availability_topic": avail_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
    }
    client.publish(power_cfg_topic, json.dumps(power_cfg), qos=0, retain=True)

    # Energy (total kWh)
    energy_uid = f"{device_id}_energy_total"
    energy_cfg_topic = f"{prefix}/sensor/{energy_uid}/config"
    energy_cfg = {
        "name": f"{inverter_name} Solar energy (total)",
        "unique_id": energy_uid,
	"default_entity_id": "sensor.solar_energy_total",
        "state_topic": energy_state,
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "availability_topic": avail_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
    }
    client.publish(energy_cfg_topic, json.dumps(energy_cfg), qos=0, retain=True)


def mqtt_publish_values(client, cfg, inverter_name, info):
    """Publish Pac (W) and EnergyTotal (kWh) for one inverter."""
    if not client or not info:
        return
    base = cfg.get('mqtt', 'base_topic', fallback='growatt/solar').rstrip('/')
    retain = cfg.getboolean('mqtt', 'retain', fallback=True)

    try:
        pac = info.get('Pac')
        if pac is not None:
            client.publish(f"{base}/{inverter_name}/power_w", str(int(round(float(pac)))), qos=0, retain=retain)
    except Exception:
        pass

    try:
        et = info.get('EnergyTotal')
        if et is not None:
            client.publish(f"{base}/{inverter_name}/energy_kwh", f"{float(et):.3f}", qos=0, retain=retain)
    except Exception:
        pass

def mqtt_publish_discovery_extra(client, cfg, inverter_name):
    if not client or not cfg.getboolean('mqtt', 'ha_discovery', fallback=True):
        return
    base   = cfg.get('mqtt', 'base_topic', fallback='growatt/solar').rstrip('/')
    prefix = cfg.get('mqtt', 'ha_prefix',  fallback='homeassistant').rstrip('/')
    root_id   = cfg.get('mqtt', 'device_id',   fallback='growatt_1000s')
    root_name = cfg.get('mqtt', 'device_name', fallback='Growatt Inverter')
    avail = f"{base}/availability"

    device_id = f"{root_id}_{inverter_name}"
    device = {
        "identifiers": [device_id],
        "manufacturer": "Growatt",
        "model": "1000S",
        "name": f"{root_name} ({inverter_name})",
    }

    # topic suffix -> (friendly name, unit, device_class, state_class)
    items = {
        "pv/power_w":        ("PV Power",            "W",  "power",       "measurement"),
        "pv1/voltage_v":     ("PV1 Voltage",         "V",  "voltage",     "measurement"),
        "pv1/current_a":     ("PV1 Current",         "A",  "current",     "measurement"),
        "ac/voltage_v":      ("AC Voltage",          "V",  "voltage",     "measurement"),
        "ac/current_a":      ("AC Current",          "A",  "current",     "measurement"),
        "grid/frequency_hz": ("Grid Frequency",      "Hz", None,          "measurement"),
        "inverter/temp_c":   ("Inverter Temperature","°C", "temperature", "measurement"),
        "energy/today_kwh":  ("Energy Today",        "kWh","energy",      "total"),
        "status/text":       ("Inverter Status",     None, None,          None),
        "status/code":       ("Inverter Status Code",None, None,          None),
    }

    for suffix, (name, uom, dev_class, state_class) in items.items():
        uid = f"{device_id}_" + suffix.replace("/", "_")
        topic_cfg = f"{prefix}/sensor/{uid}/config"
        state_topic = f"{base}/{inverter_name}/{suffix}"
        cfg_msg = {
            "name": name,
            "unique_id": uid,
            "state_topic": state_topic,
            "availability_topic": avail,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        if uom:         cfg_msg["unit_of_measurement"] = uom
        if dev_class:   cfg_msg["device_class"] = dev_class
        if state_class: cfg_msg["state_class"] = state_class
        client.publish(topic_cfg, json.dumps(cfg_msg), qos=0, retain=True)


def mqtt_publish_extra(client, cfg, inverter_name, info: dict):
    if not client or not info:
        return
    base   = cfg.get('mqtt', 'base_topic', fallback='growatt/solar').rstrip('/')
    retain = cfg.getboolean('mqtt', 'retain', fallback=True)

    to_send = {
        "pv/power_w":        info.get("Ppv"),
        "pv1/voltage_v":     info.get("Vpv1"),
        "pv1/current_a":     info.get("PV1Curr"),
        "ac/voltage_v":      info.get("Vac1"),
        "ac/current_a":      info.get("Iac1"),
        "grid/frequency_hz": info.get("Fac"),
        "inverter/temp_c":   info.get("Temp"),
        "energy/today_kwh":  info.get("EnergyToday"),
        "status/text":       info.get("Status"),
        "status/code":       info.get("StatusCode"),
    }

    # formatting per type
    formatters = {
        "pv/power_w":        lambda v: f"{float(v):.0f}",
        "pv1/voltage_v":     lambda v: f"{float(v):.1f}",
        "pv1/current_a":     lambda v: f"{float(v):.2f}",
        "ac/voltage_v":      lambda v: f"{float(v):.1f}",
        "ac/current_a":      lambda v: f"{float(v):.2f}",
        "grid/frequency_hz": lambda v: f"{float(v):.2f}",
        "inverter/temp_c":   lambda v: f"{float(v):.1f}",
        "energy/today_kwh":  lambda v: f"{float(v):.3f}",
        "status/text":       lambda v: str(v),
        "status/code":       lambda v: str(int(v)),
    }

    for suffix, val in to_send.items():
        if val is None:
            continue
        try:
            payload = formatters[suffix](val)
            client.publish(f"{base}/{inverter_name}/{suffix}", payload, qos=0, retain=retain)
        except Exception:
            continue

# ---------------- existing code (unchanged where possible) ----------------
settings = RawConfigParser()
settings.read(os.path.dirname(os.path.realpath(__file__)) + '/solarmon.cfg')

interval = settings.getint('query', 'interval', fallback=1)
offline_interval = settings.getint('query', 'offline_interval', fallback=60)
error_interval = settings.getint('query', 'error_interval', fallback=60)

db_name = settings.get('influx', 'db_name', fallback='inverter')
measurement = settings.get('influx', 'measurement', fallback='inverter')

# Clients
print('Setup Serial Connection... ', end='')
port = settings.get('solarmon', 'port', fallback='/dev/ttyUSB0')
client = ModbusClient(method='rtu', port=port, baudrate=9600, stopbits=1, parity='N', bytesize=8, timeout=1)
client.connect()
print('Done!')

# MQTT (optional)
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

    # Publish HA discovery once per inverter
    if mqtt_client:
        mqtt_publish_discovery(mqtt_client, settings, name)
        mqtt_publish_discovery_extra(mqtt_client, settings, name)

print('Done!')

while True:
    online = False
    for inverter in inverters:
        if inverter['error_sleep'] > 0:
            inverter['error_sleep'] -= interval
            continue

        growatt = inverter['growatt']
        try:
            now = time.time()
            info = growatt.read()

            if info is None:
                continue

            online = True

            # MQTT publish (live values for HA)
            if mqtt_client:
                mqtt_publish_values(mqtt_client, settings, inverter['name'], info)
                mqtt_publish_extra(mqtt_client, settings, inverter['name'], info)

        except Exception as err:
            print(growatt.name)
            print(err)
            inverter['error_sleep'] = error_interval

    if online:
        time.sleep(interval)
    else:
        time.sleep(offline_interval)
