import asyncio
import json
import math
import struct
import time
import unittest

import numpy as np

from realtime.api import APIServer, ws_frame
from realtime.association import StrictAssociator
from realtime.beast import BeastFrame, BeastParser
from realtime.clock_sync import Link, T4
from realtime.config import BEAST_HZ, C, ORDER, STATIONS
from realtime.localization import BlindLocalizer, D7C
from realtime.receiver import ReceiverServer
from realtime.state import StateStore, utc
from realtime.tracker import TrackManager
from realtime.modes.decoder import decode_modes
from realtime.modes.realtime import RealtimeModeSAssociator
from realtime.modes.tracker import ModeSTrackManager


def escaped_frame(frame_type, decoded):
    return b"\x1a" + bytes([frame_type]) + decoded.replace(b"\x1a", b"\x1a\x1a")


def modeac_frame(station, tick, raw=b"\x12\x34", mono=1.0, wall=1.0):
    return BeastFrame(station, 0x31, "modeac", tick + 244, tick, 100, raw, mono, wall)

def modes_frame(station,tick,raw=bytes.fromhex("5dabcdef000000"),mono=1.0,wall=1.0):
    return BeastFrame(station,0x32,"modes_short",tick+768,tick,100,raw,mono,wall)


class IdentityClock:
    def normalize(self, station, tick):
        return float(tick)

    def sigma(self, a, b):
        return 1.0

    class Model:
        quality = "PASS"

    def model(self, a, b):
        return self.Model()


class BeastTests(unittest.TestCase):
    def test_chunk_boundaries_and_multiple_frames(self):
        one = bytes.fromhex("000000000100641234")
        two = bytes.fromhex("00000000020065abcd")
        stream = escaped_frame(0x31, one) + escaped_frame(0x31, two)
        parser = BeastParser()
        output = []
        for chunk in (stream[:1], stream[1:5], stream[5:11], stream[11:]):
            output.extend(parser.feed(chunk))
        self.assertEqual([(x[0], x[1][-2:]) for x in output], [(0x31, b"\x12\x34"), (0x31, b"\xab\xcd")])

    def test_escaped_beast_byte(self):
        decoded = bytes.fromhex("00001a000100641a34")
        output = BeastParser().feed(escaped_frame(0x31, decoded))
        self.assertEqual(output, [(0x31, decoded)])


class ReceiverTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_and_bounded_queue(self):
        state = StateStore(STATIONS)
        queue = asyncio.Queue(maxsize=1)
        server = ReceiverServer("T37", 0, state, queue, lambda *a, **k: None)
        await server.start()
        port = server.server.sockets[0].getsockname()[1]
        frame = escaped_frame(0x31, bytes.fromhex("000000000100641234"))
        for _ in range(2):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(frame + frame)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.03)
        await server.stop()
        rs = state.receivers["T37"]
        self.assertGreaterEqual(rs.reconnect_count, 1)
        self.assertEqual(queue.qsize(), 1)
        self.assertGreater(state.stats["frames_dropped_queue"], 0)


class AssociationTests(unittest.TestCase):
    def test_strict_four_receiver_association(self):
        state = StateStore(STATIONS)
        association = StrictAssociator(IdentityClock(), state)
        target = np.array(T4.geodetic_to_ecef(20.5, 107.0, 10000))
        distance = {
            name: float(np.linalg.norm(target - association.ecef[name])) for name in ORDER
        }
        base = 1_000_000_000
        event = None
        classification = None
        for index, station in enumerate(ORDER):
            tick = base + round((distance[station] - distance[ORDER[0]]) / C * BEAST_HZ)
            event, classification = association.add(modeac_frame(station, tick, mono=index, wall=100 + index / 1000))
        self.assertEqual(classification, "STRICT_4RX")
        self.assertEqual(set(event["nodes"]), set(ORDER))
        association.prune(now=10.0, max_age_s=1.0)
        self.assertEqual(sum(len(items) for rows in association.rows.values() for items in rows.values()), 0)
        self.assertFalse(association.used)

    def test_modes_exact_payload_four_receiver_association(self):
        state=StateStore(STATIONS);association=RealtimeModeSAssociator(IdentityClock(),state)
        target=np.array(T4.geodetic_to_ecef(20.5,107.0,10000));distance={name:float(np.linalg.norm(target-np.array(T4.geodetic_to_ecef(STATIONS[name].lat,STATIONS[name].lon,STATIONS[name].alt_m)))) for name in ORDER};base=1_000_000_000
        for index,station in enumerate(ORDER):
            tick=base+round((distance[station]-distance[ORDER[0]])/C*BEAST_HZ);event,classification=association.add(modes_frame(station,tick,mono=index,wall=100+index/1000))
        self.assertEqual(classification,"STRICT_4RX");self.assertEqual(event["df"],11);self.assertEqual(event["icao"],"abcdef");self.assertEqual(set(event["nodes"]),set(ORDER));self.assertEqual(association.size(),0)

class ModeSDecoderTests(unittest.TestCase):
    def test_df11_direct_identity_and_metadata(self):
        decoded=decode_modes(bytes.fromhex("5dabcdef000000"));self.assertEqual(decoded["df"],11);self.assertEqual(decoded["icao"],"abcdef");self.assertEqual(decoded["icao_source"],"DIRECT");self.assertFalse(decoded["position_bearing"])


class LocalizerTests(unittest.TestCase):
    def test_high_residual_branch_is_rejected(self):
        original = D7C.solve

        def bad_solve(alt, stations, measured):
            residuals = {pair: 10.0 for pair in __import__("itertools").combinations(ORDER, 2)}
            candidate = {"lat": 20.0, "lon": 107.0, "rms_us": 10.0, "residuals": residuals, "center_km": 10.0, "condition": 10.0}
            return 1, [candidate], candidate

        D7C.solve = bad_solve
        try:
            result = BlindLocalizer(IdentityClock()).solve({"tdoa": {}})
        finally:
            D7C.solve = original
        self.assertEqual(result["classification"], "BLIND_INCONSISTENT")


class ClockTests(unittest.TestCase):
    def test_discontinuity_rejection_and_reset(self):
        link = Link("T37", "QK4")
        for tick in range(1000, 1030):
            link.add(tick, tick + 50)
        self.assertIsNotNone(link.slope)
        link.add(1030, 1030 + 5000)
        link.add(1031, 1031 + 5000)
        self.assertEqual(len(link.samples), 30)
        link.add(1032, 1032 + 5000)
        self.assertEqual(len(link.samples), 1)
        self.assertEqual(link.resets, 1)


class TrackerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = StateStore(STATIONS)
        self.tracker = TrackManager(self.state, lambda *a, **k: None)

    def event(self, when, raw="1234"):
        return {"raw_hex": raw, "utc": when, "utc_iso": utc(when)}

    def solution(self, lat, lon):
        return {"lat": lat, "lon": lon, "weighted_rms": 0.5, "clock_quality": "PASS", "branch_margin": 2.0}

    async def test_creation_confirmation_and_expiration(self):
        now = time.time()
        track = await self.tracker.update(self.event(now), self.solution(20.0, 107.0))
        await self.tracker.update(self.event(now + 1), self.solution(20.001, 107.0))
        await self.tracker.update(self.event(now + 2), self.solution(20.002, 107.0))
        self.assertEqual(track["state"], "CONFIRMED")
        track["last_seen_epoch"] = time.time() - 121
        await self.tracker.expire()
        self.assertFalse(self.state.tracks)

    async def test_same_code_distant_targets_stay_separate(self):
        now = time.time()
        first = await self.tracker.update(self.event(now), self.solution(20.0, 107.0))
        second = await self.tracker.update(self.event(now + 1), self.solution(21.0, 108.0))
        self.assertNotEqual(first["track_id"], second["track_id"])
        self.assertEqual(len(self.state.tracks), 2)


class APITests(unittest.TestCase):
    def test_websocket_serialization(self):
        encoded = ws_frame({"type": "track_updated", "track": {"track_id": "MAC-000001"}})
        self.assertEqual(encoded[0], 0x81)
        length = encoded[1] & 0x7F
        self.assertEqual(json.loads(encoded[2:2 + length]), {"type": "track_updated", "track": {"track_id": "MAC-000001"}})

    def test_api_schema(self):
        state = StateStore(STATIONS)
        clock = type("Clock", (), {"links": {}})()
        tracker = TrackManager(state, lambda *a, **k: None)
        api = APIServer(state, tracker, clock)
        self.assertTrue({"status", "uptime_s", "receivers_connected", "strict_4rx_enabled"} <= set(api.snapshot("/health", "")))
        self.assertEqual(len(api.snapshot("/api/receivers", "")["receivers"]), 4)
        self.assertIn("tracks", api.snapshot("/api/modeac/tracks", "min_quality=HIGH"))
        self.assertIn("strict_4rx_per_min", api.snapshot("/api/modeac/stats", ""))

    def test_modes_api_is_additive(self):
        state=StateStore(STATIONS);clock=type("Clock",(),{"links":{}})();tracker=TrackManager(state,lambda *a,**k:None);modes=ModeSTrackManager(state,lambda *a,**k:None);api=APIServer(state,tracker,clock,modes)
        self.assertIn("tracks",api.snapshot("/api/modes/tracks",""));stats=api.snapshot("/api/modes/stats","");self.assertIn("df_distribution",stats);self.assertIn("latency_ms",stats);self.assertIn("event_queue_high_water",stats["buffers"])


if __name__ == "__main__":
    unittest.main()
