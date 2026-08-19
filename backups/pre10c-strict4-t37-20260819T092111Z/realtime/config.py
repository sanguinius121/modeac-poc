from dataclasses import dataclass
from pathlib import Path

ROOT = Path("/home/mlatserver/modeac-poc")
BEAST_HZ = 12_000_000.0
C = 299_792_458.0

@dataclass(frozen=True)
class Station:
    name: str
    port: int
    lat: float
    lon: float
    alt_m: float

STATIONS = {
    "T37": Station("T37", 29996, 21.485594, 107.773191, 60.0),
    "QK4": Station("QK4", 29997, 18.760032, 105.659087, 20.0),
    "Dao_Cai_chien": Station("Dao_Cai_chien", 29998, 21.320940, 107.766116, 28.0),
    "BachLongVi": Station("BachLongVi", 29999, 20.132285, 107.724413, 28.0),
}
ORDER = ["T37", "Dao_Cai_chien", "QK4", "BachLongVi"]
API_HOST = "0.0.0.0"
API_PORT = 8090
FRAME_QUEUE_SIZE = 50_000
MODES_EVENT_QUEUE_SIZE = 64
MODES_SOLVER_WORKERS = 3
MODES_EVENT_STALE_S = 3.0
MODES_BUFFER_AGE_S = 1.0
MODES_MAX_PAYLOADS = 20_000
PUBLISH_DF17_MLAT = False
MODEAC_PER_STATION = 4_000
CLOCK_SAMPLES_PER_LINK = 2_000
CLOCK_MIN_SAMPLES = 100
ASSOCIATION_MARGIN_US = 10.0
ALTITUDE_GRID_FT = [0, 5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000, 45000]
TRACK_CONFIRM_FIXES = 3
TRACK_STALE_S = 30.0
TRACK_EXPIRE_S = 120.0
TRACK_MAX_GAP_S = 120.0
TRACK_HARD_SPEED_MPS = 450.0
TRACK_GATE_ALLOWANCE_M = 2_000.0
