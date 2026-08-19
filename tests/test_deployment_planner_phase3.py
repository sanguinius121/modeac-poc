import json
import math
import unittest
from pathlib import Path

from deployment_planner.backend.api import (
    CURRENT_RECEIVERS,
    DEFAULT_POLYGON,
    analyze_payload,
    analyze_point_payload,
)
from deployment_planner.backend.geometry_engine import _best_key, _worst_key
from deployment_planner.backend.models import AnalyzeRequest
from deployment_planner.reception import outline_store


ROOT = Path(__file__).resolve().parents[1]
REAL_OUTLINE = ROOT / "tests" / "fixtures" / "readsb-outline-real-sanitized.json"


def receiver(rid, lat, lon, **updates):
    value = {
        "id": rid,
        "name": rid.upper(),
        "lat": lat,
        "lon": lon,
        "altitude_m": 30,
        "reception_model": "simulated",
        "max_range_km": 2000,
        "enabled": True,
    }
    value.update(updates)
    return value


def synthetic_receivers(n):
    # Five perimeter sites plus center and a seventh off-axis site.
    points = [(19, 107), (19, 109), (21, 109), (21, 107),
              (20, 110), (20, 108), (22, 108.5)]
    return [receiver("r%d" % (i + 1), *points[i]) for i in range(n)]


def payload(receivers, **updates):
    value = {
        "receivers": receivers,
        "surveillance_polygon": [[19.9, 107.9], [19.9, 108.1],
                                 [20.1, 108.1], [20.1, 107.9]],
        "target_altitude_m": 2500,
        "timing_noise_us": 0.25,
        "grid_step_km": 20,
        "geometry_receiver_ids": [x["id"] for x in receivers[:4]],
        "geometry_strategy": "best_4_of_n",
    }
    value.update(updates)
    return value


class EnumerationAndRankingTests(unittest.TestCase):
    def test_combination_counts_for_four_through_seven(self):
        for n, expected in ((4, 1), (5, 5), (6, 15), (7, 35)):
            result = analyze_payload(payload(synthetic_receivers(n)))
            self.assertEqual(result["summary"]["maximum_subsets_per_point"], expected)
            self.assertTrue(all(x["subset_count"] == expected for x in result["grid"]))

    def test_only_reception_eligible_receivers_enter_subsets(self):
        receivers = synthetic_receivers(5)
        receivers[-1]["max_range_km"] = 1
        result = analyze_payload(payload(receivers))
        for point in result["grid"]:
            self.assertEqual(point["subset_count"], 1)
            self.assertNotIn("r5", point["best_subset"])

    def test_branch_safe_best_ranking_and_deterministic_tie_break(self):
        unsafe = {"subset_ids": ["a", "b", "c", "d"], "branch_safe": False,
                  "p95_error_m": 10, "condition": 1, "inside_hull": True}
        safe_z = {**unsafe, "subset_ids": ["z", "b", "c", "d"],
                  "branch_safe": True, "p95_error_m": 100}
        safe_a = {**safe_z, "subset_ids": ["a", "b", "c", "e"]}
        self.assertIs(min((unsafe, safe_z), key=_best_key), safe_z)
        self.assertIs(min((safe_z, safe_a), key=_best_key), safe_a)

    def test_worst_ranking_prefers_unsafe_then_larger_error(self):
        safe = {"subset_ids": ["a"], "branch_safe": True,
                "p95_error_m": 5000, "condition": 20, "inside_hull": False}
        unsafe = {"subset_ids": ["b"], "branch_safe": False,
                  "p95_error_m": 100, "condition": 2, "inside_hull": True}
        self.assertIs(max((safe, unsafe), key=_worst_key), unsafe)

    def test_five_rx_leave_one_out_and_n_minus_one(self):
        result = analyze_payload(payload(synthetic_receivers(5)))
        point = result["grid"][0]
        self.assertEqual(point["subset_count"], 5)
        dropped = {tuple(sorted(set(point["available_receiver_ids"]) - set(x)))
                   for x in [point["best_subset"], point["worst_subset"]]}
        self.assertTrue(dropped)
        detail = analyze_point_payload({**payload(synthetic_receivers(5)),
                                        "point": [point["lat"], point["lon"]]})
        self.assertEqual(len(detail["subsets"]), 5)
        self.assertEqual({tuple(sorted(set(point["available_receiver_ids"]) - set(x["subset_ids"])))
                          for x in detail["subsets"]},
                         {("r1",), ("r2",), ("r3",), ("r4",), ("r5",)})
        self.assertEqual(point["n_minus_1_survivable"],
                         all(x["quality"] == "GOOD" for x in detail["subsets"]))


class ApiProviderAndRegressionTests(unittest.TestCase):
    def test_4ofn_does_not_require_four_strict_baseline_ids(self):
        body = payload(synthetic_receivers(5), geometry_receiver_ids=["r1"])
        result = analyze_payload(body)
        self.assertEqual(result["summary"]["maximum_subsets_per_point"], 5)

    def test_strict_backward_compatibility_is_exact(self):
        base = {
            "receivers": [dict(x) for x in CURRENT_RECEIVERS],
            "surveillance_polygon": [list(x) for x in DEFAULT_POLYGON],
            "target_altitude_m": 2500,
            "timing_noise_us": 0.25,
            "grid_step_km": 20,
            "geometry_receiver_ids": [x["id"] for x in CURRENT_RECEIVERS],
        }
        old = analyze_payload(base)
        explicit = analyze_payload({**base, "geometry_strategy": "strict_4"})
        old["summary"].pop("analysis_seconds")
        explicit["summary"].pop("analysis_seconds")
        self.assertEqual(old, explicit)

    def test_receiver_failure_is_temporary_and_reduces_n(self):
        body = payload(synthetic_receivers(5))
        before = analyze_payload(body)
        after = analyze_payload({**body, "failed_receiver_id": "r5"})
        self.assertEqual(before["summary"]["maximum_subsets_per_point"], 5)
        self.assertEqual(after["summary"]["maximum_subsets_per_point"], 1)
        self.assertTrue(body["receivers"][-1]["enabled"])

    def test_full_n_is_diagnostic_not_primary(self):
        result = analyze_payload(payload(synthetic_receivers(6),
                                         geometry_strategy="full_n_diagnostic"))
        point = result["grid"][0]
        self.assertIsNotNone(point["full_n_condition"])
        self.assertIsNotNone(point["full_n_predicted_p95_m"])
        self.assertEqual(point["quality"], point["best_quality"])

    def test_high_n_guard_does_not_truncate(self):
        receivers = [receiver("h%d" % i, 18 + (i % 3), 105 + i * .3)
                     for i in range(10)]
        with self.assertRaisesRegex(ValueError, r"C\(10,4\)=210"):
            analyze_payload(payload(receivers))

    def test_mixed_outline_and_simulated_4ofn(self):
        resource = outline_store.create(REAL_OUTLINE.read_bytes(), "phase3-outline.json")
        try:
            receivers = [receiver("o%d" % i, 20.5 + .3 * (i % 2),
                                  105.3 + .7 * (i // 2),
                                  reception_model="outline",
                                  outline_id=resource["outline_id"],
                                  outline_filename="phase3-outline.json",
                                  outline_source="upload") for i in range(4)]
            receivers.append(receiver("candidate", 21.0, 105.8))
            body = payload(receivers,
                           surveillance_polygon=[[20.98, 105.75], [20.98, 105.80],
                                                 [21.03, 105.80], [21.03, 105.75]])
            result = analyze_payload(body)
            self.assertEqual(result["summary"]["reception_source_counts"],
                             {"simulated": 1, "outline": 4})
            self.assertTrue(all(x["subset_count"] == 5 for x in result["grid"]))
        finally:
            outline_store.delete(resource["outline_id"])

    def test_phase3_frontend_contracts(self):
        root = ROOT / "deployment_planner" / "frontend"
        html = (root / "index.html").read_text()
        js = (root / "app.js").read_text()
        for token in ("best_4_of_n", "worst_4_of_n", "full_n_diagnostic",
                      "failed-receiver", "Good Subset Count", "N-1 Survivability",
                      "Receiver Importance"):
            self.assertIn(token, html)
        for token in ("/api/analyze-point", "Show all subsets", "good_subset_fraction",
                      "n_minus_1_survivable", "allow_high_subset_count"):
            self.assertIn(token, js)


if __name__ == "__main__":
    unittest.main()
