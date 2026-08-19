"""Incremental Beast binary stream parser with validated timestamp corrections."""
from dataclasses import dataclass

FRAME_LENGTH = {0x31: 9, 0x32: 14, 0x33: 21}
CORRECTION = {0x31: 244, 0x32: 768, 0x33: 768}
KIND = {0x31: "modeac", 0x32: "modes_short", 0x33: "modes_long"}

@dataclass
class BeastFrame:
    station: str
    frame_type: int
    kind: str
    timestamp_raw: int
    timestamp_corrected: int
    signal: int
    payload: bytes
    arrival_monotonic: float
    arrival_utc: float

class BeastParser:
    def __init__(self):
        self.buffer = bytearray()
        self.parse_errors = 0

    def feed(self, data: bytes):
        self.buffer.extend(data); output=[]
        while True:
            try:start=self.buffer.index(0x1A)
            except ValueError:
                if self.buffer:self.parse_errors+=1
                self.buffer.clear();break
            if start:
                self.parse_errors+=start;del self.buffer[:start]
            if len(self.buffer)<2:break
            typ=self.buffer[1]
            if typ==0x1A:del self.buffer[:2];continue
            needed=FRAME_LENGTH.get(typ)
            if needed is None:self.parse_errors+=1;del self.buffer[0];continue
            decoded=bytearray();i=2;bad=False
            while len(decoded)<needed:
                if i>=len(self.buffer):break
                b=self.buffer[i]
                if b==0x1A:
                    if i+1>=len(self.buffer):break
                    if self.buffer[i+1]!=0x1A:
                        self.parse_errors+=1;del self.buffer[:i];bad=True;break
                    i+=2
                else:i+=1
                decoded.append(b)
            if bad:continue
            if len(decoded)<needed:break
            del self.buffer[:i];output.append((typ,bytes(decoded)))
        return output

def decode_frame(station, typ, raw, mono, utc):
    ts=int.from_bytes(raw[:6],"big");corrected=0 if ts==0 else ts-CORRECTION[typ]
    return BeastFrame(station,typ,KIND[typ],ts,corrected,raw[6],raw[7:],mono,utc)
