import unittest

from realtime.beast import CORRECTION, decode_frame
from realtime.clock_sync import Link
from tools.phase10a_common import (
    BASELINE_SUBSET,
    ORDER,
    STATIONS,
    SUBSETS,
    cluster_transmissions,
    public_family,
    subset_name,
    summarize_family,
    unique_any4,
)


def observations(stations=ORDER, raw_hex="5dabcdef123456", base_tick=1_000_000, df=11):
    result = []
    for index, station in enumerate(stations):
        result.append(
            {
                "id": f"{station}:{base_tick}",
                "station": station,
                "ts": base_tick + index * 12,
                "utc_ns": base_tick * 1000 + index,
                "raw_hex": raw_hex,
                "df": df,
            }
        )
    return result


class Phase10AConfigTests(unittest.TestCase):
    def test_five_receiver_mapping(self):
        self.assertEqual(len(STATIONS), 5)
        self.assertEqual(STATIONS["MongCai"].port, 29995)
        self.assertAlmostEqual(STATIONS["MongCai"].lat, 21.550206)
        self.assertAlmostEqual(STATIONS["MongCai"].lon, 107.938978)
        self.assertEqual(STATIONS["MongCai"].alt_m, 36.0)

    def test_exact_five_four_receiver_subsets(self):
        self.assertEqual(len(SUBSETS), 5)
        self.assertEqual(len(set(SUBSETS)), 5)
        self.assertIn(BASELINE_SUBSET, SUBSETS)

    def test_beast_timestamp_corrections_are_unchanged(self):
        self.assertEqual(CORRECTION[0x31], 244)
        self.assertEqual(CORRECTION[0x32], 768)
        self.assertEqual(CORRECTION[0x33], 768)
        for typ, correction, length in ((0x31, 244, 9), (0x32, 768, 14), (0x33, 768, 21)):
            raw = (10_000).to_bytes(6, "big") + bytes([10]) + bytes(length - 7)
            frame = decode_frame("MongCai", typ, raw, 1.0, 2.0)
            self.assertEqual(frame.timestamp_corrected, 10_000 - correction)

    def test_clock_quality_threshold_reuse(self):
        link = Link("T37", "MongCai")
        for tick in range(100):
            link.add(1_000_000 + tick * 10_000, 2_000_000 + tick * 10_000)
        self.assertEqual(link.quality, "STRONG")
        self.assertLess(link.public()["p95_us"], 1.0)


class Phase10AAssociationTests(unittest.TestCase):
    def setUp(self):
        self.transforms = {station: (1.0, 0.0) for station in ORDER}

    def test_strict_five_receiver_cluster(self):
        clusters, diagnostics = cluster_transmissions(observations(), self.transforms)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["receiver_count"], 5)
        self.assertEqual(diagnostics["observations_used"], 5)

    def test_exact_payload_is_mandatory(self):
        rows = observations(ORDER[:2], raw_hex="aa", base_tick=1_000_000)
        rows += observations(ORDER[2:], raw_hex="bb", base_tick=1_000_000)
        clusters, _ = cluster_transmissions(rows, self.transforms)
        self.assertFalse(any(cluster["receiver_count"] == 5 for cluster in clusters))

    def test_repeated_transmissions_do_not_reuse_observations(self):
        rows = observations(base_tick=1_000_000) + observations(base_tick=100_000_000)
        clusters, diagnostics = cluster_transmissions(rows, self.transforms)
        self.assertEqual([cluster["receiver_count"] for cluster in clusters], [5, 5])
        used = [node["id"] for cluster in clusters for node in cluster["nodes"].values()]
        self.assertEqual(len(used), len(set(used)))
        self.assertEqual(diagnostics["observations_used"], 10)

    def test_ambiguous_near_equal_candidate_is_rejected(self):
        rows = observations(ORDER[:2])
        duplicate = dict(rows[1])
        duplicate["id"] += ":duplicate"
        duplicate["ts"] += 1
        rows.append(duplicate)
        _, diagnostics = cluster_transmissions(rows, self.transforms)
        self.assertGreater(diagnostics.get("ambiguous", 0), 0)

    def test_short_baseline_physical_violation_is_not_retained(self):
        rows = observations()
        for row in rows:
            if row["station"] == "Dao_Cai_chien":
                row["ts"] += 2_000
        clusters, diagnostics = cluster_transmissions(rows, self.transforms)
        self.assertGreater(diagnostics.get("physical_reject", 0), 0)
        self.assertFalse(
            any(
                "T37" in cluster["nodes"] and "Dao_Cai_chien" in cluster["nodes"]
                for cluster in clusters
            )
        )

    def test_association_is_deterministic(self):
        rows = observations() + observations(raw_hex="8d1234", base_tick=100_000_000, df=17)
        first, first_diagnostics = cluster_transmissions(rows, self.transforms)
        second, second_diagnostics = cluster_transmissions(list(reversed(rows)), self.transforms)
        projection = lambda values: [
            (cluster["raw_hex"], tuple(cluster["nodes"])) for cluster in values
        ]
        self.assertEqual(projection(first), projection(second))
        self.assertEqual(first_diagnostics, second_diagnostics)

    def test_five_rx_populates_every_four_receiver_subset_once(self):
        summary = summarize_family(observations(), self.transforms, 3.0)
        self.assertEqual(summary["strict_5rx"], 1)
        self.assertEqual(summary["any_4_of_5"], 1)
        self.assertEqual(summary["baseline_fixed_4rx"], 1)
        self.assertTrue(all(value == 1 for value in summary["subset_counts"].values()))

    def test_any4_recovers_event_missing_from_current_baseline(self):
        alternative = ("T37", "Dao_Cai_chien", "QK4", "MongCai")
        summary = summarize_family(observations(alternative), self.transforms, 3.0)
        self.assertEqual(summary["baseline_fixed_4rx"], 0)
        self.assertEqual(summary["any_4_of_5"], 1)
        self.assertEqual(summary["absolute_increase"], 1)
        self.assertIsNone(summary["percent_increase"])

    def test_baseline_fixed_four_regression(self):
        rows = observations(BASELINE_SUBSET)
        summary = summarize_family(rows, self.transforms, 3.0)
        self.assertEqual(summary["subset_counts"][subset_name(BASELINE_SUBSET)], 1)
        self.assertEqual(summary["baseline_fixed_4rx"], 1)

    def test_any4_component_deduplicates_five_subset_views(self):
        summary = summarize_family(observations(), self.transforms, 3.0)
        components = unique_any4(summary["_subset_clusters"])
        self.assertEqual(len(components), 1)
        self.assertEqual(len(components[0]), 5)

    def test_df_specific_counting_can_be_separated(self):
        rows = observations(raw_hex="800001", df=16)
        rows += observations(raw_hex="880001", base_tick=100_000_000, df=17)
        df16 = public_family(
            summarize_family([row for row in rows if row["df"] == 16], self.transforms, 3.0)
        )
        df17 = public_family(
            summarize_family([row for row in rows if row["df"] == 17], self.transforms, 3.0)
        )
        self.assertEqual(df16["any_4_of_5"], 1)
        self.assertEqual(df17["any_4_of_5"], 1)
        self.assertEqual(df16["observations"], 5)


if __name__ == "__main__":
    unittest.main()
