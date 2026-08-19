import asyncio
import itertools
import json
import subprocess
import sys
import unittest

from realtime.api import APIServer
from realtime.clock_sync import ClockSynchronizer
from realtime.config import STATIONS as DEFAULT_STATIONS
from realtime.modes.decoder import decode_modes
from realtime.pre10c_config import ORDER, PROFILE_NAME, REFERENCE, SOLVE_DFS, STATIONS
from realtime.state import StateStore
from realtime.tracker import TrackManager


class Pre10CProfileTests(unittest.TestCase):
    def test_exact_strict_quartet(self):
        self.assertEqual(ORDER, ("T37", "Dao_Cai_chien", "BachLongVi", "MongCai"))
        self.assertEqual(set(STATIONS), set(ORDER))

    def test_ports_are_exact(self):
        self.assertEqual({name: station.port for name, station in STATIONS.items()}, {
            "T37": 29996, "Dao_Cai_chien": 29998,
            "BachLongVi": 29999, "MongCai": 29995,
        })

    def test_qk_receivers_are_excluded(self):
        self.assertNotIn("QK3", STATIONS)
        self.assertNotIn("QK4", STATIONS)

    def test_t37_is_reference(self):
        self.assertEqual(REFERENCE, "T37")
        clock = ClockSynchronizer(StateStore(STATIONS), lambda *a, **k: None, STATIONS, ORDER, REFERENCE)
        self.assertEqual(clock.reference, "T37")
        self.assertEqual(len(clock.links), 6)

    def test_mongcai_clock_mapping_uses_t37_link(self):
        clock = ClockSynchronizer(StateStore(STATIONS), lambda *a, **k: None, STATIONS, ORDER, REFERENCE)
        link = clock.model("T37", "MongCai")
        link.slope = 1.000001
        link.offset = 42.0
        tick = 1234567.0
        self.assertAlmostEqual(clock.normalize("MongCai", tick), (tick - 42.0) / 1.000001)

    def test_diagnostic_df_set_includes_df16_without_forcing_df17(self):
        self.assertEqual(SOLVE_DFS, (0, 4, 5, 11, 16, 20, 21))
        self.assertNotIn(17, SOLVE_DFS)
        self.assertEqual(decode_modes(bytes([16 << 3]) + bytes(13))["df"], 16)

    def test_default_realtime_profile_is_unchanged(self):
        self.assertEqual(set(DEFAULT_STATIONS), {"T37", "QK4", "Dao_Cai_chien", "BachLongVi"})
        self.assertNotIn("MongCai", DEFAULT_STATIONS)

    def test_profile_activation_and_solver_geometry_in_clean_process(self):
        script = r'''
import json
from realtime.pre10c_config import activate
stations, order = activate()
from realtime.localization import D7C, configure_solver_geometry
configure_solver_geometry(stations, order)
target = D7C.ll_to_en(20.8, 107.8)
tdoa = D7C.predict_all(target, 3048.0)
_, candidates, _ = D7C.solve(3048.0, order, tdoa)
print(json.dumps({"order": list(order), "pairs": len(D7C.PAIRS), "best": min(x["rms_us"] for x in candidates)}))
'''
        result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        self.assertEqual(tuple(payload["order"]), ORDER)
        self.assertEqual(payload["pairs"], 6)
        self.assertLess(payload["best"], 1e-6)

    def test_modes_api_exposes_additive_solver_per_df(self):
        state = StateStore(DEFAULT_STATIONS)
        state.modes_stats["solver_attempt_df_16"] = 3
        state.modes_stats["df_16_blind_unique"] = 2
        clock = type("Clock", (), {"links": {}})()
        tracker = TrackManager(state, lambda *a, **k: None)
        modes_tracker = type("ModesTracker", (), {"public": lambda *a: {}})()
        body = APIServer(state, tracker, clock, modes_tracker).snapshot("/api/modes/stats", "")
        self.assertEqual(body["solver_by_df"]["16"]["attempts"], 3)
        self.assertEqual(body["solver_by_df"]["16"]["blind_unique"], 2)

    def test_profile_identity_is_explicit(self):
        self.assertEqual(PROFILE_NAME, "pre10c-t37-caichien-blv-mongcai")


if __name__ == "__main__":
    unittest.main()
