#!/bin/bash
# Clean up old Growatt MQTT discovery topics
# Run this on a machine that can reach the MQTT broker

MQTT_HOST="192.168.30.50"
MQTT_USER="mqtt-user"
MQTT_PASS="mqtt-pass"

# Old discovery config topics (publish empty payload with retain to clear)
TOPICS=(
  "homeassistant/sensor/growatt_1000s_main_power/config"
  "homeassistant/sensor/growatt_1000s_main_energy_total/config"
  "homeassistant/sensor/growatt_1000s_main_pv_power_w/config"
  "homeassistant/sensor/growatt_1000s_main_pv1_voltage_v/config"
  "homeassistant/sensor/growatt_1000s_main_pv1_current_a/config"
  "homeassistant/sensor/growatt_1000s_main_ac_voltage_v/config"
  "homeassistant/sensor/growatt_1000s_main_ac_current_a/config"
  "homeassistant/sensor/growatt_1000s_main_grid_frequency_hz/config"
  "homeassistant/sensor/growatt_1000s_main_inverter_temp_c/config"
  "homeassistant/sensor/growatt_1000s_main_energy_today_kwh/config"
  "homeassistant/sensor/growatt_1000s_main_status_text/config"
  "homeassistant/sensor/growatt_1000s_main_status_code/config"
)

# Old state topics
STATE_TOPICS=(
  "growatt/solar/availability"
  "growatt/solar/main/power_w"
  "growatt/solar/main/energy_kwh"
  "growatt/solar/main/pv/power_w"
  "growatt/solar/main/pv1/voltage_v"
  "growatt/solar/main/pv1/current_a"
  "growatt/solar/main/ac/voltage_v"
  "growatt/solar/main/ac/current_a"
  "growatt/solar/main/grid/frequency_hz"
  "growatt/solar/main/inverter/temp_c"
  "growatt/solar/main/energy/today_kwh"
  "growatt/solar/main/status/text"
  "growatt/solar/main/status/code"
)

echo "Clearing old discovery topics..."
for topic in "${TOPICS[@]}"; do
  mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" -t "$topic" -n -r
  echo "  Cleared: $topic"
done

echo ""
echo "Clearing old state topics..."
for topic in "${STATE_TOPICS[@]}"; do
  mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" -t "$topic" -n -r
  echo "  Cleared: $topic"
done

echo ""
echo "Done! Now remove the old 'Growatt 1000S (main)' device from HA:"
echo "  Settings > Devices > MQTT > Growatt 1000S (main) > Delete"