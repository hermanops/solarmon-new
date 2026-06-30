#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
from pymodbus.exceptions import ModbusIOException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------

StateCodes = {
    0: 'Waiting',
    1: 'Normal',
    2: 'Discharging',
    3: 'Fault'
}

ErrorCodes = {
    0: 'None',
    24: 'Auto Test Failed',
    25: 'No AC Connection',
    26: 'PV Isolation Low',
    27: 'Residual Current High',
    28: 'DC Voltage High',
    29: 'AC Voltage Outrange',
    30: 'AC Freq Outrange',
    31: 'Module Temperature High',
    32: 'Ambient Temp High',
    33: 'Fan Stuck',
    34: 'EEPROM Fail',
    35: 'Relay Check Fail',
    36: 'DCI Outrange',
    37: 'GFCI Outrange',
    38: 'GFCI Device Fail',
    39: 'PV Voltage Outrange',
}

# Some environments have the class in different places/versions
try:
    from pymodbus.pdu import ExceptionResponse
except Exception:
    class ExceptionResponse:  # fallback stub
        pass


# ---------------------------------------------------------------------------
# Helpers for register decoding
# ---------------------------------------------------------------------------

def read_single(row, index, scale=10):
    """
    Read a single 16-bit register with a default scale of 0.1 (scale=10).
    Pass scale=1 for raw integer, scale=100 for 0.01, etc.
    """
    try:
        return row.registers[index] / float(scale)
    except Exception:
        return None


def read_double(row, index, scale=10):
    """
    Read a 32-bit value composed of two 16-bit registers (index, index+1).
    Default scale 0.1 (scale=10).
    """
    try:
        hi = int(row.registers[index])
        lo = int(row.registers[index + 1])
        val = (hi << 16) | lo
        return val / float(scale)
    except Exception:
        return None


def merge(d1, d2):
    out = dict(d1)
    out.update(d2)
    return out


# ---------------------------------------------------------------------------
# Safe Modbus read helpers
# ---------------------------------------------------------------------------

def _resp_ok(resp):
    return (
        resp is not None
        and not isinstance(resp, (ModbusIOException, ExceptionResponse))
        and hasattr(resp, "registers")
    )


def _read_input_safe(client, unit, start, count, retries=2, delay=0.05):
    """
    Read input registers with a few quick retries.
    Returns a response with .registers or None if all attempts fail.
    """
    for _ in range(retries + 1):
        try:
            resp = client.read_input_registers(start, count=count, slave=unit)
            if _resp_ok(resp):
                return resp
        except Exception:
            pass
        time.sleep(delay)
    return None


# ---------------------------------------------------------------------------
# Growatt class
# ---------------------------------------------------------------------------

class Growatt:
    def __init__(self, client, name, unit):
        self.client = client
        self.name = name
        self.unit = unit
        self.modbusVersion = None
        self.read_info()

    def read_info(self):
        """Read modbus version. Non-fatal if inverter is offline (e.g. nighttime)."""
        try:
            row = self.client.read_holding_registers(73, count=1, slave=self.unit)
            if _resp_ok(row):
                self.modbusVersion = row.registers[0]
            else:
                self.modbusVersion = None
                logger.warning("[%s] Inverter not responding (offline/sleeping)", self.name)
        except Exception as e:
            self.modbusVersion = None
            logger.warning("[%s] Could not read inverter info: %s", self.name, e)

    def print_info(self):
        print('Growatt:')
        print('\tName: ' + str(self.name))
        print('\tUnit: ' + str(self.unit))
        print('\tModbus Version: ' + str(self.modbusVersion))

    def read(self):
        """
        Read the main blocks of input registers.
        Each block is read safely; if one fails we still return what we have.
        Returns None if the inverter is not responding.
        """

        # ---- Block 0..32 (core live values) ----
        row = _read_input_safe(self.client, self.unit, 0, 33)
        if row is None:
            return None

        info = {
            'StatusCode': row.registers[0],
            'Status': StateCodes.get(row.registers[0], str(row.registers[0])),
            'Ppv': read_double(row, 1),             # W (0.1)
            'Vpv1': read_single(row, 3),            # V (0.1)
            'PV1Curr': read_single(row, 4),         # A (0.1)
            'PV1Watt': read_double(row, 5),         # W (0.1)
            'Vpv2': read_single(row, 7),            # V (0.1)
            'PV2Curr': read_single(row, 8),         # A (0.1)
            'PV2Watt': read_double(row, 9),         # W (0.1)
            'Pac': read_double(row, 11),            # W (0.1)
            'Fac': read_single(row, 13, 100),       # Hz (0.01)
            'Vac1': read_single(row, 14),           # V (0.1)
            'Iac1': read_single(row, 15),           # A (0.1)
            'Pac1': read_double(row, 16),           # W (0.1)
            'Vac2': read_single(row, 18),           # V (0.1)
            'Iac2': read_single(row, 19),           # A (0.1)
            'Pac2': read_double(row, 20),           # W (0.1)
            'Vac3': read_single(row, 22),           # V (0.1)
            'Iac3': read_single(row, 23),           # A (0.1)
            'Pac3': read_double(row, 24),           # W (0.1)
            'EnergyToday': read_double(row, 26),    # kWh (0.1)
            'EnergyTotal': read_double(row, 28),    # kWh (0.1)
            'TimeTotal': read_double(row, 30, 2),   # hours? (scale 2 in original)
            'Temp': read_single(row, 32),           # °C (0.1)
        }

        # ---- Block 33..40 (fault values + code) ----
        row = _read_input_safe(self.client, self.unit, 33, 8)
        if _resp_ok(row):
            fault_code = row.registers[7]
            info = merge(info, {
                'ISOFault': read_single(row, 0),
                'GFCIFault': read_single(row, 1, 1),
                'DCIFault': read_single(row, 2, 100),
                'VpvFault': read_single(row, 3),
                'VavFault': read_single(row, 4),
                'FacFault': read_single(row, 5, 100),
                'TempFault': read_single(row, 6),
                'FaultCode': fault_code,
                'Fault': ErrorCodes.get(fault_code, str(fault_code)),
            })

        # ---- Block 42..43 (bus voltages) ----
        row = _read_input_safe(self.client, self.unit, 42, 2)
        if _resp_ok(row):
            info = merge(info, {
                'PBusV': read_single(row, 0),
                'NBusV': read_single(row, 1),
            })

        # ---- Block 48..63 (energies & reactive) ----
        row = _read_input_safe(self.client, self.unit, 48, 16)
        if _resp_ok(row):
            info = merge(info, {
                'Epv1_today': read_double(row, 0),
                'Epv1_total': read_double(row, 2),
                'Epv2_today': read_double(row, 4),
                'Epv2_total': read_double(row, 6),
                'Epv_total': read_double(row, 8),
                'Rac': read_double(row, 10),
                'E_rac_today': read_double(row, 12),
                'E_rac_total': read_double(row, 14),
            })

        return info