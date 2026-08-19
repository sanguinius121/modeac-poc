import unittest

from realtime.association import StrictAssociator
from realtime.beast import BeastFrame
from realtime.clock_sync import ClockSynchronizer
from realtime.config import STATIONS as PRODUCTION_STATIONS
from realtime.modes.association import cluster_transmissions
from realtime.nrx_association import NrxAssociationBuffer, associate_observations
from realtime.state import StateStore
from tools.phase10a_common import BASELINE_SUBSET, ORDER, STATIONS


TRANSFORMS = {station: (1.0, 0.0) for station in ORDER}


class IdentityClock:
    def normalize(self, station, tick):
        return float(tick)


def observations(receivers=ORDER, key="5dabcdef123456", tick=1_000_000, df=11):
    return [
        {
            "id": f"{station}:{tick}",
            "station": station,
            "tick": tick + index * 12,
            "utc_ns": tick * 1000 + index,
            "mono": index / 100.0,
            "raw_hex": key,
            "df": df,
            "family": "modes",
        }
        for index, station in enumerate(receivers)
    ]


def associate(rows, receivers=ORDER):
    return associate_observations(rows, TRANSFORMS, receivers, STATIONS, 3.0)


class GenericNrxBatchTests(unittest.TestCase):
    def test_generic_four_receiver_cluster_model(self):
        result = associate(observations(BASELINE_SUBSET), BASELINE_SUBSET)
        cluster = result.clusters[0]
        self.assertEqual(cluster.receiver_count, 4)
        self.assertEqual(cluster.receiver_ids, BASELINE_SUBSET)
        self.assertEqual(tuple(cluster.observations_by_receiver), BASELINE_SUBSET)
        self.assertEqual(tuple(cluster.normalized_timestamps), BASELINE_SUBSET)

    def test_one_five_receiver_transmission_is_one_cluster(self):
        result = associate(observations())
        self.assertEqual(len(result.clusters), 1)
        self.assertEqual(result.clusters[0].receiver_count, 5)
        self.assertEqual(result.counters["5RX"], 1)
        self.assertEqual(result.counters["4RX"], 0)

    def test_receiver_order_and_cluster_identity_are_deterministic(self):
        rows = observations()
        first = associate(rows).clusters[0]
        second = associate(list(reversed(rows))).clusters[0]
        self.assertEqual(first.receiver_ids, ORDER)
        self.assertEqual(first.cluster_id, second.cluster_id)

    def test_mode_s_requires_exact_payload(self):
        rows = observations(ORDER[:2], key="aa") + observations(ORDER[2:], key="bb")
        result = associate(rows)
        self.assertFalse(any(cluster.receiver_count == 5 for cluster in result.clusters))

    def test_physical_timing_violation_removes_incompatible_receiver(self):
        rows = observations()
        next(row for row in rows if row["station"] == "Dao_Cai_chien")["tick"] += 2_000
        result = associate(rows)
        self.assertGreater(result.diagnostics.get("physical_reject", 0), 0)
        self.assertFalse(any(
            "T37" in cluster.receiver_ids and "Dao_Cai_chien" in cluster.receiver_ids
            for cluster in result.clusters
        ))

    def test_duplicate_raw_code_ambiguity_is_rejected(self):
        rows = observations(ORDER[:2], key="1234")
        duplicate = dict(rows[1]); duplicate["id"] += ":dup"; duplicate["tick"] += 1
        rows.append(duplicate)
        result = associate(rows)
        self.assertGreater(result.diagnostics.get("ambiguous", 0), 0)

    def test_duplicate_observation_id_is_not_reused(self):
        rows = observations()
        rows.append(dict(rows[0]))
        result = associate(rows)
        used = [
            node["id"] for cluster in result.clusters
            for node in cluster.observations_by_receiver.values()
        ]
        self.assertEqual(len(used), len(set(used)))
        self.assertEqual(result.diagnostics.get("duplicate_observation_id"), 1)

    def test_repeated_exact_payload_creates_two_disjoint_transmissions(self):
        rows = observations(tick=1_000_000) + observations(tick=100_000_000)
        result = associate(rows)
        self.assertEqual([cluster.receiver_count for cluster in result.clusters], [5, 5])
        ids = [node["id"] for c in result.clusters for node in c.observations_by_receiver.values()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_df_specific_and_membership_counters(self):
        rows = observations(df=16)
        result = associate(rows)
        self.assertEqual(result.counters["per_df"]["16"]["5RX"], 1)
        self.assertEqual(result.counters["receiver_membership"]["+".join(ORDER)], 1)

    def test_empty_and_partial_receiver_cases(self):
        self.assertEqual(len(associate([]).clusters), 0)
        one = associate(observations(ORDER[:1]))
        self.assertEqual(len(one.clusters), 0)

    def test_no_solver_subset_enumeration_in_cluster(self):
        cluster = associate(observations()).clusters[0]
        self.assertFalse(hasattr(cluster, "subsets"))
        self.assertEqual(cluster.receiver_count, 5)

    def test_fixed_four_compatibility_wrapper_matches_generic_core(self):
        rows = observations(BASELINE_SUBSET)
        generic = associate(rows, BASELINE_SUBSET)
        legacy, _ = cluster_transmissions(
            rows,
            {station: TRANSFORMS[station] for station in BASELINE_SUBSET},
            order=BASELINE_SUBSET,
            stations={station: STATIONS[station] for station in BASELINE_SUBSET},
        )
        self.assertEqual(len(legacy), len(generic.clusters))
        self.assertEqual(legacy[0]["receiver_ids"], list(BASELINE_SUBSET))
        self.assertIn("association_latency_ms", legacy[0])
        state = StateStore(PRODUCTION_STATIONS)
        modeac = StrictAssociator(IdentityClock(), state)
        event = None
        for index, row in enumerate(rows):
            frame = BeastFrame(
                row["station"], 0x31, "modeac", row["tick"] + 244,
                row["tick"], 100, b"\x12\x34", index / 100.0, 100 + index / 1000.0,
            )
            event, classification = modeac.add(frame)
        self.assertEqual(classification, "STRICT_4RX")
        self.assertEqual(set(event["nodes"]), set(BASELINE_SUBSET))


class GenericNrxBufferTests(unittest.TestCase):
    def buffer(self, **kwargs):
        return NrxAssociationBuffer(
            ORDER, STATIONS, TRANSFORMS, 3.0,
            minimum_receivers=kwargs.pop("minimum_receivers", 2),
            settle_s=kwargs.pop("settle_s", 0.1),
            max_age_s=kwargs.pop("max_age_s", 1.0),
            **kwargs,
        )

    def test_delayed_fifth_receiver_joins_before_emission(self):
        buffer = self.buffer()
        rows = observations()
        for row in rows[:4]:
            self.assertEqual(buffer.add(row, now=row["mono"]), [])
        emitted = buffer.add(rows[4], now=0.04)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].receiver_count, 5)
        self.assertEqual(buffer.size(), 0)

    def test_settled_four_receiver_candidate_emits_once(self):
        buffer = self.buffer()
        for row in observations(BASELINE_SUBSET):
            buffer.add(row, now=row["mono"])
        emitted = buffer.flush(now=0.2)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].receiver_count, 4)
        self.assertEqual(buffer.flush(now=0.3), [])

    def test_consumed_observation_cannot_be_added_again(self):
        buffer = self.buffer()
        rows = observations()
        for row in rows:
            buffer.add(row, now=row["mono"])
        self.assertEqual(buffer.size(), 0)
        self.assertEqual(buffer.add(rows[0], now=0.2), [])
        self.assertEqual(buffer.diagnostics["observation_reuse_rejected"], 1)

    def test_expired_partial_row_is_cleaned(self):
        buffer = self.buffer(minimum_receivers=2, max_age_s=0.2)
        buffer.add(observations(ORDER[:1])[0], now=0.0)
        self.assertEqual(buffer.size(), 1)
        self.assertEqual(buffer.prune(now=0.3), [])
        self.assertEqual(buffer.size(), 0)
        self.assertEqual(buffer.diagnostics["expired_rows"], 1)

    def test_payload_capacity_remains_bounded(self):
        buffer = self.buffer(max_payloads=2, max_age_s=0.05)
        for index, key in enumerate(("aa", "bb", "cc")):
            row = observations(ORDER[:1], key=key, tick=1_000_000 + index)[0]
            buffer.add(row, now=index * 0.1)
        self.assertLessEqual(len(buffer.rows), 2)


class GenericClockReadinessTests(unittest.TestCase):
    def test_missing_non_reference_pair_does_not_block_receiver(self):
        state = StateStore(STATIONS)
        clock = ClockSynchronizer(state, lambda *args, **kwargs: None, STATIONS, ORDER)
        for station in ORDER[1:]:
            link = clock.model("T37", station)
            link.slope = 1.0; link.offset = 0.0
        self.assertIsNone(clock.model("QK4", "MongCai").slope)
        self.assertTrue(clock.receiver_ready("MongCai"))
        self.assertTrue(clock.ready())
        self.assertEqual(clock.usable_receivers(), ORDER)


if __name__ == "__main__":
    unittest.main()
