import json
import math
import unittest
from pathlib import Path

from deployment_planner.backend.api import coverage_area_payload
from deployment_planner.backend.coverage_area import (
    EARTH_RADIUS_KM,
    geodesic_circle_area_km2,
    polygon_area_km2,
    polygon_intersection_area_km2,
    receiver_coverage_summary,
)
from deployment_planner.reception.outline import OutlineError, parse_readsb_outline


def simulated(rid="sim",lat=20,lon=107,radius=350):
    return {"id":rid,"name":rid.upper(),"lat":lat,"lon":lon,"altitude_m":30,
            "reception_model":"simulated","max_range_km":radius,"enabled":True}


def outlined(oid="outline-test"):
    return {"id":"outline","name":"OUTLINE","lat":20,"lon":107,"altitude_m":30,
            "reception_model":"outline","max_range_km":350,"outline_id":oid,
            "outline_filename":"outline.json","outline_source":"upload","enabled":True}


class FakeOutlineStore:
    def __init__(self,ring):self.resource={"rings":[ring],"metadata":{"filename":"outline.json"}}
    def public(self,oid):
        if oid!="outline-test":raise OutlineError(f"Unknown outline_id: {oid}")
        return self.resource


class CoverageAreaMathTests(unittest.TestCase):
    def test_simulated_350_km_uses_spherical_cap_area(self):
        expected=2*math.pi*EARTH_RADIUS_KM**2*(1-math.cos(350/EARTH_RADIUS_KM))
        self.assertAlmostEqual(geodesic_circle_area_km2(350),expected,places=6)
        self.assertTrue(384_000<expected<386_000)

    def test_outline_polygon_area_is_reasonable(self):
        area=polygon_area_km2([[0,0],[0,1],[1,1],[1,0]])
        self.assertTrue(12_300<area<12_450)

    def test_coordinate_order_is_latitude_longitude_not_swapped(self):
        high_latitude=polygon_area_km2([[60,10],[60,11],[61,11],[61,10]])
        swapped=polygon_area_km2([[10,60],[10,61],[11,61],[11,60]])
        self.assertLess(high_latitude,swapped*.6)

    def test_surveillance_polygon_area_is_equal_area_result(self):
        result=coverage_area_payload({"receivers":[],"surveillance_polygon":[[0,0],[0,1],[1,1],[1,0]]})
        self.assertAlmostEqual(result["surveillance_area_km2"],polygon_area_km2([[0,0],[0,1],[1,1],[1,0]]))
        self.assertEqual(result["area_method"],"spherical_lambert_azimuthal_equal_area")

    def test_polygon_intersection_area(self):
        first=[[0,0],[0,2],[2,2],[2,0]];second=[[1,1],[1,3],[3,3],[3,1]]
        intersection=polygon_intersection_area_km2(first,second)
        expected=polygon_area_km2([[1,1],[1,2],[2,2],[2,1]])
        self.assertAlmostEqual(intersection,expected,delta=expected*.002)

    def test_percentage_uses_surveillance_area_as_denominator(self):
        polygon=[[19.9,106.9],[19.9,107.1],[20.1,107.1],[20.1,106.9]]
        result=receiver_coverage_summary([simulated(radius=350)],polygon,FakeOutlineStore(polygon));row=result["receivers"][0]
        self.assertAlmostEqual(row["coverage_inside_surveillance_km2"],result["surveillance_area_km2"],delta=1)
        self.assertAlmostEqual(row["surveillance_coverage_percent"],100,places=3)
        self.assertGreater(row["coverage_area_km2"],row["coverage_inside_surveillance_km2"])

    def test_mixed_receiver_summary_preserves_source_semantics(self):
        outline_ring=[[19.5,106.5],[19.5,107.5],[20.5,107.5],[20.5,106.5]]
        result=receiver_coverage_summary([simulated(),outlined()],outline_ring,FakeOutlineStore(outline_ring))
        self.assertEqual([row["reception_model"] for row in result["receivers"]],["simulated","outline"])
        self.assertEqual(result["receivers"][0]["source_label_vi"],"Vùng thu giả định")
        self.assertEqual(result["receivers"][1]["source_label_vi"],"Vùng thu quan sát từ readsb")

    def test_no_surveillance_polygon_returns_null_intersection_fields(self):
        result=receiver_coverage_summary([simulated()],None,FakeOutlineStore([[0,0],[0,1],[1,0]]));row=result["receivers"][0]
        self.assertIsNone(result["surveillance_area_km2"])
        self.assertIsNone(row["coverage_inside_surveillance_km2"])
        self.assertIsNone(row["surveillance_coverage_percent"])

    def test_existing_invalid_outline_validation_is_unchanged(self):
        raw=json.dumps({"actualRange":{"last24h":{"points":[[20,107],[21,108],[20,108],[21,107]]}}}).encode()
        with self.assertRaisesRegex(OutlineError,"self-intersects"):parse_readsb_outline(raw)


class Phase36FrontendContractTests(unittest.TestCase):
    def test_receiver_cards_and_network_summary_expose_area_semantics(self):
        js=Path("deployment_planner/frontend/app.js").read_text(encoding="utf-8")
        for token in ("Diện tích vùng thu","Diện tích trong vùng giám sát","Tỷ lệ bao phủ vùng giám sát",
                      "Vùng thu giả định","Vùng thu quan sát từ readsb","/api/coverage-areas",
                      "Mẫu số của tỷ lệ là toàn bộ diện tích vùng giám sát"):
            self.assertIn(token,js)


if __name__=="__main__":unittest.main()
