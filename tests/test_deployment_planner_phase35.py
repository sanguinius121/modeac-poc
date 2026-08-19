import json
import unittest
from pathlib import Path

from deployment_planner.backend.api import analyze_payload
from deployment_planner.backend.assessment import (
    UX_THRESHOLDS,
    _dependency,
    _percent_level,
    _p95_dimension,
    build_assessment,
)
from deployment_planner.backend.models import AnalyzeRequest


ROOT = Path(__file__).resolve().parents[1]


def receiver(index):
    points = [
        (19.0, 107.0), (19.0, 109.0), (21.0, 109.0),
        (21.0, 107.0), (20.0, 110.0), (20.0, 108.0),
    ]
    lat, lon = points[index]
    return {
        "id": f"r{index + 1}", "name": f"RX-{index + 1}",
        "lat": lat, "lon": lon, "altitude_m": 30,
        "reception_model": "simulated", "max_range_km": 2000,
        "enabled": True,
    }


def payload(count=5, **updates):
    receivers = [receiver(i) for i in range(count)]
    value = {
        "receivers": receivers,
        "surveillance_polygon": [
            [19.8, 107.8], [19.8, 108.2],
            [20.2, 108.2], [20.2, 107.8],
        ],
        "target_altitude_m": 2500,
        "timing_noise_us": 0.25,
        "grid_step_km": 20,
        "geometry_receiver_ids": [x["id"] for x in receivers[:4]],
        "geometry_strategy": "best_4_of_n",
    }
    value.update(updates)
    return value


def summary(**updates):
    value = {
        "geometry_strategy": "best_4_of_n",
        "grid_points": 100,
        "four_plus_rx_coverage_percent": 90.0,
        "five_plus_rx_coverage_percent": 80.0,
        "six_plus_rx_coverage_percent": 0.0,
        "good_percent": 75.0,
        "good_acceptable_percent": 92.0,
        "worst_good_percent": 50.0,
        "n_minus_1_survivable_percent": 65.0,
        "one_good_subset_percent": 75.0,
        "robust_good_fraction_percent": 60.0,
        "three_good_subsets_percent": 40.0,
        "median_good_subset_fraction": 0.6,
        "median_best_p50_m": 150.0,
        "median_best_p95_m": 300.0,
        "p90_best_p95_m": 900.0,
        "median_best_condition": 8.0,
        "best_branch_safe_percent": 90.0,
        "best_branch_good_percent": 80.0,
        "best_inside_hull_percent": 70.0,
        "reception_source_counts": {"simulated": 5, "outline": 0},
        "receiver_importance": [],
    }
    value.update(updates)
    return value


class VietnameseFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend = ROOT / "deployment_planner" / "frontend"
        cls.html = (frontend / "index.html").read_text()
        cls.js = (frontend / "app.js").read_text()

    def test_basic_is_default_and_major_labels_are_vietnamese(self):
        self.assertIn('<body class="basic-mode">', self.html)
        for text in (
            "Bộ quy hoạch triển khai MLAT", "Cơ bản", "Nâng cao",
            "Số trạm thu được tín hiệu", "Chất lượng tốt nhất",
            "Sai số dự kiến 95%", "Khả năng chịu mất 1 trạm",
            "Mức độ phụ thuộc trạm", "Phân tích mạng",
        ):
            self.assertIn(text, self.html + self.js)

    def test_advanced_retains_phase3_technical_values(self):
        for token in (
            "Condition Number", "Branch separation", "Inside convex hull",
            "Full-N P50 / P95 / condition", "/api/analyze-point",
            "good_subset_fraction", "n_minus_1_survivable",
        ):
            self.assertIn(token, self.js)
        self.assertIn("advanced-only", self.html)

    def test_quality_translation_and_help_contract(self):
        expected = {
            "GOOD": "TỐT", "ACCEPTABLE": "CHẤP NHẬN ĐƯỢC",
            "POOR": "KÉM", "VERY_POOR": "RẤT KÉM",
            "NO_MLAT": "KHÔNG ĐỦ ĐIỀU KIỆN MLAT",
        }
        for key, label in expected.items():
            self.assertIn(f'{key}:"{label}"', self.js)
        for term in (
            "Vùng thu chung", "Độ tách biệt nghiệm", "P50", "P95",
            "Tổ hợp 4-of-N", "N-1", "Phụ thuộc trạm",
        ):
            self.assertIn(term, self.html)

    def test_mode_switch_rerenders_without_analyze_call(self):
        start = self.js.index("function setDisplayMode")
        end = self.js.index("function removeReceptionLayers", start)
        function = self.js[start:end]
        self.assertIn("renderGrid();renderSummary();renderAssessment()", function)
        self.assertNotIn("/api/analyze", function)


class AssessmentRuleTests(unittest.TestCase):
    def request(self, count=5):
        return AnalyzeRequest.parse(payload(count))

    def assess(self, **changes):
        return build_assessment({"summary": summary(**changes)}, self.request())

    def test_assessment_is_byte_deterministic_for_same_input(self):
        body = payload(5)
        first = analyze_payload(body)["assessment"]
        second = analyze_payload(body)["assessment"]
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )

    def test_reception_threshold_boundaries(self):
        thresholds = UX_THRESHOLDS["reception_percent"]
        self.assertEqual(_percent_level(90, thresholds), "RAT_TOT")
        self.assertEqual(_percent_level(89.999, thresholds), "TOT")
        self.assertEqual(_percent_level(75, thresholds), "TOT")
        self.assertEqual(_percent_level(50, thresholds), "TRUNG_BINH")
        self.assertEqual(_percent_level(25, thresholds), "KEM")
        self.assertEqual(_percent_level(24.999, thresholds), "RAT_KEM")

    def test_p95_thresholds_consider_median_and_map_tail(self):
        self.assertEqual(_p95_dimension(250, 500, .25)["level"], "RAT_TOT")
        self.assertEqual(_p95_dimension(500, 1500, .25)["level"], "TOT")
        self.assertEqual(_p95_dimension(1500, 5000, .25)["level"], "TRUNG_BINH")
        self.assertEqual(_p95_dimension(5000, 6000, .25)["level"], "KEM")
        self.assertEqual(_p95_dimension(5001, 6000, .25)["level"], "RAT_KEM")

    def test_branch_n_minus_one_and_overall_caps(self):
        strong = self.assess()
        self.assertEqual(strong["branch"]["level"], "TOT")
        self.assertEqual(strong["n_minus_1"]["level"], "TOT")
        low_reception = self.assess(four_plus_rx_coverage_percent=20)
        self.assertEqual(low_reception["overall"]["level"], "KEM")
        no_n_minus_one = self.assess(n_minus_1_survivable_percent=0)
        self.assertNotIn(no_n_minus_one["overall"]["level"], ("TOT", "RAT_TOT"))
        strict = build_assessment(
            {"summary": {
                **summary(), "geometry_strategy": "strict_4",
                "median_predicted_p50_m": 100,
                "median_predicted_p95_m": 200,
                "p90_predicted_p95_m": 400,
                "median_condition": 5,
                "branch_safe_percent": 100,
                "branch_good_percent": 100,
            }},
            AnalyzeRequest.parse(payload(5, geometry_strategy="strict_4")),
        )
        self.assertEqual(strict["n_minus_1"]["level"], "KHONG_AP_DUNG")
        self.assertNotIn(strict["overall"]["level"], ("TOT", "RAT_TOT"))

    def test_tradeoffs_are_stated(self):
        result = self.assess(
            median_best_p95_m=400, p90_best_p95_m=3000,
            good_percent=80, worst_good_percent=20,
            n_minus_1_survivable_percent=5,
        )
        paragraph = result["paragraph_vi"]
        self.assertIn("sai số tăng mạnh", paragraph)
        self.assertIn("chất lượng giữa các tổ hợp chưa đồng đều", paragraph)
        self.assertIn("5,0% vùng", paragraph)


class DependencyTests(unittest.TestCase):
    @staticmethod
    def item(rid, median, p90, samples=20, fraction=50):
        return {
            "id": rid, "name": rid.upper(),
            "median_p95_ratio_without_receiver": median,
            "p90_p95_ratio_without_receiver": p90,
            "samples": samples, "sample_fraction_percent": fraction,
        }

    def test_one_clear_critical_receiver(self):
        result = _dependency({"receiver_importance": [
            self.item("a", 1.2, 1.4), self.item("qk4", 2.8, 4.0),
        ]})
        self.assertEqual(result["receiver_id"], "qk4")
        self.assertIn("2,80 lần", result["text_vi"])

    def test_equal_importance_has_deterministic_tie(self):
        result = _dependency({"receiver_importance": [
            self.item("b", 2, 3), self.item("a", 2, 3),
        ]})
        self.assertEqual(result["receiver_id"], "a")
        self.assertTrue(result["tied"])
        self.assertIn("đồng hạng", result["text_vi"])

    def test_insufficient_samples_are_not_ranked(self):
        result = _dependency({"receiver_importance": [
            self.item("only", 9, 10, samples=1),
        ]})
        self.assertEqual(result["level"], "KHONG_DU_DU_LIEU")
        self.assertIsNone(result["receiver_id"])

    def test_receiver_unused_by_best_is_not_called_critical(self):
        result = _dependency({"receiver_importance": [
            self.item("unused", 1.0, 1.0), self.item("other", 1.0, 1.0),
        ]})
        self.assertIsNone(result["receiver_id"])
        self.assertIn("Chưa thấy một trạm phụ thuộc nổi trội", result["text_vi"])


if __name__ == "__main__":
    unittest.main()
