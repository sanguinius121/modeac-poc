"""Readsb-compatible metadata extraction for useful Mode-S downlink formats."""
from realtime.clock_sync import T4


def crc_residual(payload):
    """Return the 24-bit Mode-S CRC syndrome (AP-recovered address for AP DFs)."""
    value = int.from_bytes(payload, "big")
    bits = len(payload) * 8
    polynomial = 0xFFF409
    for bit in range(bits - 1, 23, -1):
        if value & (1 << bit):
            value ^= polynomial << (bit - 24)
    return value & 0xFFFFFF


def _altitude_13(ac13):
    """Decode Q=1 Mode-S AC13 altitude; Gillham Q=0 remains unavailable."""
    if not ac13 or not (ac13 & 0x10):
        return None
    n = ((ac13 & 0x1F80) >> 2) | ((ac13 & 0x20) >> 1) | (ac13 & 0x0F)
    return n * 25 - 1000


def _identity_13(id13):
    # Same pulse mapping validated against readsb in Test 7E.
    a = ((id13 >> 7) & 1) * 4 + ((id13 >> 9) & 1) * 2 + ((id13 >> 11) & 1)
    b = ((id13 >> 1) & 1) * 4 + ((id13 >> 3) & 1) * 2 + ((id13 >> 5) & 1)
    c = ((id13 >> 8) & 1) * 4 + ((id13 >> 10) & 1) * 2 + ((id13 >> 12) & 1)
    d = ((id13 >> 0) & 1) * 4 + ((id13 >> 2) & 1) * 2 + ((id13 >> 4) & 1)
    return "%d%d%d%d" % (a, b, c, d)


def decode_modes(payload):
    if len(payload) not in (7, 14):
        return None
    df = payload[0] >> 3
    direct = df in (11, 17)
    icao = payload[1:4].hex() if direct else "%06x" % crc_residual(payload)
    source = "DIRECT" if direct else "PARITY_RESIDUAL_UNVALIDATED"
    result = {
        "df": df,
        "icao": icao,
        "icao_source": source,
        "raw_hex": payload.hex(),
        "message_length": len(payload),
        "type_code": None,
        "position_bearing": False,
        "altitude_bearing": False,
        "squawk_bearing": False,
        "altitude_ft": None,
        "squawk": None,
        "odd": None,
        "lat_cpr": None,
        "lon_cpr": None,
    }
    if df == 17:
        result["type_code"] = payload[4] >> 3
        airborne = T4.decode_airborne_fields(payload)
        if airborne:
            result.update(
                position_bearing=True,
                altitude_bearing=True,
                altitude_ft=airborne["altitude_ft"],
                odd=airborne["odd"],
                lat_cpr=airborne["lat_cpr"],
                lon_cpr=airborne["lon_cpr"],
            )
    elif df in (4, 20):
        ac13 = (int.from_bytes(payload, "big") >> (len(payload) * 8 - 32)) & 0x1FFF
        result["altitude_bearing"] = True
        result["altitude_ft"] = _altitude_13(ac13)
    elif df in (5, 21):
        id13 = (int.from_bytes(payload, "big") >> (len(payload) * 8 - 32)) & 0x1FFF
        result["squawk_bearing"] = True
        result["squawk"] = _identity_13(id13)
    return result
