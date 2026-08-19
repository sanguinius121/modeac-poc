import json
import math
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

from deployment_planner.backend.api import CURRENT_RECEIVERS, DEFAULT_POLYGON, Handler, analyze_payload
from deployment_planner.backend.coverage import ground_distance_km, reception
from deployment_planner.backend.geometry_engine import (
    MC_DRAWS,
    MC_SEED,
    analyze,
    collinear,
    quality_class,
    surveillance_grid,
)
from deployment_planner.backend.models import AnalyzeRequest, Receiver, ValidationError
import geometry_core as core


def payload(**updates):
    value = {
        "receivers": [dict(x) for x in CURRENT_RECEIVERS],
        "surveillance_polygon": [list(x) for x in DEFAULT_POLYGON],
        "target_altitude_m": 2500,
        "timing_noise_us": 0.25,
        "grid_step_km": 20,
        "geometry_receiver_ids": [x["id"] for x in CURRENT_RECEIVERS],
    }
    value.update(updates)
    return value


class InputAndCoverageTests(unittest.TestCase):
    def test_receiver_validation_and_outline_reference_requirement(self):
        with self.assertRaises(ValidationError):
            Receiver.parse({**CURRENT_RECEIVERS[0], "lat": 91})
        with self.assertRaises(ValidationError):
            Receiver.parse({**CURRENT_RECEIVERS[0], "enabled": "yes"})
        with self.assertRaisesRegex(ValidationError, "missing outline"):
            Receiver.parse({**CURRENT_RECEIVERS[0], "reception_model": "outline"})

    def test_requires_exactly_four_manual_geometry_receivers(self):
        with self.assertRaisesRegex(ValidationError, "exactly four"):
            AnalyzeRequest.parse(payload(geometry_receiver_ids=["rx-t37"] * 3))

    def test_disabled_geometry_receiver_is_rejected(self):
        receivers = [dict(x) for x in CURRENT_RECEIVERS]
        receivers[0]["enabled"] = False
        with self.assertRaisesRegex(ValidationError, "enabled"):
            AnalyzeRequest.parse(payload(receivers=receivers))

    def test_horizontal_ground_distance_reception_gate(self):
        receiver = Receiver.parse({**CURRENT_RECEIVERS[0], "max_range_km": 100})
        near_distance, near = reception(receiver, receiver.lat, receiver.lon + 0.5)
        far_distance, far = reception(receiver, receiver.lat, receiver.lon + 1.5)
        self.assertLess(near_distance, 100)
        self.assertTrue(near)
        self.assertGreater(far_distance, 100)
        self.assertFalse(far)
        self.assertAlmostEqual(ground_distance_km(0, 0, 0, 1), 111.195, places=2)

    def test_polygon_grid_generation_and_metadata(self):
        points, metadata = surveillance_grid([(20, 107), (20, 107.5), (20.5, 107.5), (20.5, 107)], 20)
        self.assertGreater(len(points), 1)
        self.assertGreater(metadata["area_km2"], 2500)
        self.assertEqual(metadata["bounding_box"]["south"], 20)


class GeometryTests(unittest.TestCase):
    @staticmethod
    def stations(points):
        return {f"R{i}": (lat, lon, 30) for i, (lat, lon) in enumerate(points)}

    def test_hull_condition_predicted_error_and_quality(self):
        square = self.stations([(19.5, 106.5), (19.5, 107.5), (20.5, 107.5), (20.5, 106.5)])
        draws = np.random.default_rng(MC_SEED).normal(size=(4, MC_DRAWS))
        metric = core.geometry_metrics(20, 107, 2500, square, 0.25, draws)
        self.assertTrue(math.isfinite(metric["condition"]))
        self.assertGreater(metric["mc_p95_m"], 0)
        self.assertEqual(quality_class(metric["mc_p95_m"], metric["condition"], 2), "GOOD")

    def test_linear_receivers_are_detected_for_branch_safety(self):
        receivers = tuple(Receiver.parse({"id": f"r{i}", "name": f"R{i}", "lat": 20, "lon": 106 + i * .5, "altitude_m": 30, "reception_model": "simulated", "max_range_km": 350, "enabled": True}) for i in range(4))
        self.assertTrue(collinear(receivers))
        metric = core.geometry_metrics(20.5, 107, 2500, {r.id: (r.lat, r.lon, r.altitude_m) for r in receivers}, 0.25)
        # The local Jacobian may remain finite on a curved Earth; the planner's
        # explicit collinearity/remote-branch gate is what rejects the mirror.
        self.assertTrue(math.isfinite(metric["condition"]))

    def test_outside_hull_and_close_pair_are_worse(self):
        balanced = self.stations([(19.5, 106.5), (19.5, 107.5), (20.5, 107.5), (20.5, 106.5)])
        close_pair = self.stations([(19.5, 106.5), (19.5001, 106.5001), (20.5, 107.5), (20.5, 106.5)])
        center = core.geometry_metrics(20, 107, 2500, balanced, 0.25)
        outside = core.geometry_metrics(22, 109, 2500, balanced, 0.25)
        close = core.geometry_metrics(20, 107, 2500, close_pair, 0.25)
        self.assertGreater(outside["condition"], center["condition"])
        self.assertGreater(close["mc_p95_m"], center["mc_p95_m"])

    def test_no_mlat_when_one_selected_receiver_is_out_of_range(self):
        receivers = [{**x, "max_range_km": 1 if i == 0 else 350} for i, x in enumerate(CURRENT_RECEIVERS)]
        small = [[20.0, 107.0], [20.0, 107.4], [20.4, 107.4], [20.4, 107.0]]
        result = analyze_payload(payload(receivers=receivers, surveillance_polygon=small))
        self.assertTrue(result["grid"])
        self.assertTrue(all(x["quality"] == "NO_MLAT" for x in result["grid"]))

    def test_linear_analysis_is_json_safe_and_conservative(self):
        receivers = [{"id": f"r{i}", "name": f"R{i}", "lat": 20, "lon": 106.5 + i * .3, "altitude_m": 30, "reception_model": "simulated", "max_range_km": 350, "enabled": True} for i in range(4)]
        result = analyze_payload(payload(receivers=receivers, geometry_receiver_ids=[x["id"] for x in receivers], surveillance_polygon=[[19.8, 106.7], [19.8, 107.2], [20.3, 107.2], [20.3, 106.7]]))
        json.dumps(result, allow_nan=False)
        available = [x for x in result["grid"] if x["quality"] != "NO_MLAT"]
        self.assertTrue(available)
        self.assertTrue(all(not x["branch_safe"] for x in available))
        self.assertTrue(all(x["quality"] in ("POOR", "VERY_POOR") for x in available))


class RegressionAndApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = analyze(AnalyzeRequest.parse(payload()))

    def test_current_network_matches_existing_geometry_core(self):
        stations = {x["id"]: (x["lat"], x["lon"], x["altitude_m"]) for x in CURRENT_RECEIVERS}
        draws = np.random.default_rng(MC_SEED).normal(size=(4, MC_DRAWS))
        rows = [x for x in self.result["grid"] if x["quality"] != "NO_MLAT"]
        self.assertTrue(rows)
        for row in rows[::max(1, len(rows) // 5)]:
            expected = core.geometry_metrics(row["lat"], row["lon"], 2500, stations, 0.25, draws)
            self.assertAlmostEqual(row["condition"], expected["condition"], places=12)
            self.assertAlmostEqual(row["predicted_p95_error_m"], expected["mc_p95_m"], places=9)

    def test_arbitrary_n_uses_only_explicit_four_for_geometry(self):
        fifth = {"id": "rx5", "name": "RX5", "lat": 20.5, "lon": 108.5, "altitude_m": 30, "reception_model": "simulated", "max_range_km": 350, "enabled": True}
        value = payload(receivers=[*CURRENT_RECEIVERS, fifth], surveillance_polygon=[[20, 107], [20, 107.3], [20.3, 107.3], [20.3, 107]])
        result = analyze_payload(value)
        self.assertEqual(result["summary"]["geometry_receiver_ids"], value["geometry_receiver_ids"])
        self.assertEqual(len(result["summary"]["receiver_contribution"]), 5)

    def test_http_api_health_preset_and_analysis(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(base + "/api/health") as response:
                self.assertEqual(json.load(response)["status"], "ok")
            body = payload(surveillance_polygon=[[20, 107], [20, 107.3], [20.3, 107.3], [20.3, 107]])
            request = urllib.request.Request(base + "/api/analyze", json.dumps(body).encode(), {"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request) as response:
                result = json.load(response)
            self.assertIn("summary", result)
            self.assertIn("grid", result)
        finally:
            server.shutdown()
            server.server_close()


class PlannerFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1] / "deployment_planner" / "frontend"
        cls.html = (root / "index.html").read_text()
        cls.js = (root / "app.js").read_text()

    def test_map_editing_and_analysis_controls_exist(self):
        for token in ("load-current", "add-receiver", "show-coverage", "clear-area", "target-altitude", "timing-noise", "grid-step", "view-mode", "analyze", "clear-results"):
            self.assertIn(f'id="{token}"', self.html)
        for token in ('draggable:true', 'L.Draw.Event.CREATED', 'data-k="lat"', 'data-k="altitude_m"', 'data-k="max_range_km"'):
            self.assertIn(token, self.js)

    def test_heatmap_details_summary_and_stale_state_exist(self):
        for token in ("Geometry Quality", "Receiver Count", "Predicted P95 Error"):
            self.assertIn(token, self.html)
        for token in ("branch_safe", "inside_hull", "predicted_p95_error_m", "good_percent", "no_mlat_percent", "Configuration changed", "QUALITY_TEXT"):
            self.assertIn(token, self.js)

    def test_config_roundtrip_and_manual_four_selection_exist(self):
        for token in ("exportConfig", "import-config", "geometry_receiver_ids", "exactly four"):
            self.assertIn(token, self.js)

    def test_clear_results_and_visible_coverage_contract(self):
        for token in ("function clearResults()", "gridLayer.clearLayers()", 'state.result=null', '$("clear-results").disabled=true'):
            self.assertIn(token, self.js)
        for token in ("weight:2", "opacity:.8", "fillOpacity:.075"):
            self.assertIn(token, self.js)

    def test_active_geometry_uses_green_marker(self):
        for token in ("ACTIVE_GEOMETRY_ICON", "active-geometry-pin", "selected?ACTIVE_GEOMETRY_ICON:DEFAULT_RECEIVER_ICON"):
            self.assertIn(token, self.js)


if __name__ == "__main__":
    unittest.main()
