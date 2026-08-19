"""Mode A rendering and Gillham candidate metadata reused from Test 7D."""
import importlib.util

from .config import ROOT


def _load_test7d():
    spec = importlib.util.spec_from_file_location(
        "realtime_test7d", ROOT / "tools/test7d-modeac-altitude.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TEST7D = _load_test7d()


def decode(raw_hex):
    """Return interpretation hints; these never participate in localization."""
    decoded = _TEST7D.decode(int(raw_hex, 16))
    plausible = decoded["mode_c_valid"] and -1000 <= decoded["mode_c_altitude_ft"] <= 60000
    return {
        "raw_code": raw_hex,
        "display_code": decoded["mode_a_code"],
        "gillham_decodable": decoded["mode_c_valid"],
        "mode_c_candidate": plausible,
        "decoded_altitude_candidate": decoded["mode_c_altitude_ft"] if plausible else None,
        "mode_interpretation": "UNKNOWN",
    }
