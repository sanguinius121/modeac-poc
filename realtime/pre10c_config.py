"""Isolated fixed-four profile for the T37/CaiChien/BLV/MongCai pre-test."""
from .config import Station

PROFILE_NAME="pre10c-t37-caichien-blv-mongcai"
REFERENCE="T37"
ORDER=("T37","Dao_Cai_chien","BachLongVi","MongCai")
STATIONS={
    "T37":Station("T37",29996,21.485594,107.773191,60.0),
    "Dao_Cai_chien":Station("Dao_Cai_chien",29998,21.320940,107.766116,28.0),
    "BachLongVi":Station("BachLongVi",29999,20.132285,107.724413,28.0),
    "MongCai":Station("MongCai",29995,21.550206,107.938978,36.0),
}
SOLVE_DFS=(0,4,5,11,16,20,21)

def activate():
    """Activate before importing realtime modules that bind config constants."""
    from . import config
    config.STATIONS.clear();config.STATIONS.update(STATIONS)
    config.ORDER[:]=ORDER
    return config.STATIONS,tuple(config.ORDER)
