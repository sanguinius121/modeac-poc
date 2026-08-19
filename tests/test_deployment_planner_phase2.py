import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from deployment_planner.backend.api import CURRENT_RECEIVERS, Handler, analyze_payload
from deployment_planner.backend.models import AnalyzeRequest, ValidationError
from deployment_planner.reception import outline_store
from deployment_planner.reception.outline import MAX_UPLOAD_BYTES, OutlineError, parse_readsb_outline, point_in_ring, points_in_ring

ROOT = Path(__file__).resolve().parents[1]
REAL_FIXTURE = ROOT / "tests" / "fixtures" / "readsb-outline-real-sanitized.json"


def outline_bytes(points):
    return json.dumps({"actualRange":{"last24h":{"points":[[*p, 30000] for p in points]}}}).encode()


def square(south=19.5, west=106.5, north=20.5, east=107.5):
    return [(south,west),(south,east),(north,east),(north,west)]


def payload(receivers, polygon=None, selected=None, step=20):
    return {"receivers":receivers,"surveillance_polygon":polygon or [[19.7,106.7],[19.7,107.3],[20.3,107.3],[20.3,106.7]],"target_altitude_m":2500,"timing_noise_us":.25,"grid_step_km":step,"geometry_receiver_ids":selected or [x["id"] for x in receivers[:4]]}


class RealOutlineParserTests(unittest.TestCase):
    def test_verified_real_readsb_schema_coordinate_order_and_containment(self):
        rings,metadata,_=parse_readsb_outline(REAL_FIXTURE.read_bytes(),REAL_FIXTURE.name)
        self.assertEqual(metadata["schema_path"],"actualRange.last24h.points")
        self.assertEqual(metadata["coordinate_order"],"latitude,longitude,third_value_unused")
        self.assertEqual(metadata["point_count"],60)
        self.assertEqual(rings[0][0],[24.0951,105.7465])
        self.assertTrue(point_in_ring(21.024587,105.773481,rings[0]))
        self.assertFalse(point_in_ring(0,0,rings[0]))
        self.assertEqual(points_in_ring([(21.024587,105.773481),(0,0)],rings[0]).tolist(),[True,False])
        self.assertEqual(metadata["third_value"]["maximum"],41100)
        self.assertFalse(metadata["third_value"]["used_for_eligibility"])

    def test_normalization_removes_adjacent_duplicate_and_closing_point(self):
        raw=outline_bytes([(20,107),(20,108),(20,108),(21,108),(21,107),(20,107)])
        rings,metadata,_=parse_readsb_outline(raw)
        self.assertEqual(metadata["point_count"],4)
        self.assertNotEqual(rings[0][0],rings[0][-1])

    def test_malformed_schema_coordinates_and_small_polygon_are_rejected(self):
        cases=[b"not json",b"{}",outline_bytes([(20,107),(21,108)]),outline_bytes([(20,107),(20,108),(91,108)]),b'{"actualRange":{"last24h":{"points":[[NaN,107],[20,108],[21,107]]}}}']
        for raw in cases:
            with self.subTest(raw=raw[:30]),self.assertRaises(OutlineError):parse_readsb_outline(raw)

    def test_self_intersection_and_size_limit(self):
        with self.assertRaisesRegex(OutlineError,"self-intersects"):parse_readsb_outline(outline_bytes([(20,107),(21,108),(20,108),(21,107)]))
        with self.assertRaisesRegex(OutlineError,"byte limit"):parse_readsb_outline(b" "*(MAX_UPLOAD_BYTES+1))


class OutlineApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),Handler);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.base=f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()

    def upload(self,raw,filename="outline.json"):
        boundary="----planner-test-boundary"
        body=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/json\r\n\r\n".encode()+raw+f"\r\n--{boundary}--\r\n".encode())
        request=urllib.request.Request(self.base+"/api/outlines",body,{"Content-Type":f"multipart/form-data; boundary={boundary}"},method="POST")
        with urllib.request.urlopen(request) as response:return response.status,json.load(response)

    def test_upload_get_list_delete_lifecycle_and_metadata(self):
        status,resource=self.upload(REAL_FIXTURE.read_bytes(),"station-outline.json");oid=resource["outline_id"]
        try:
            self.assertEqual(status,201);self.assertTrue(resource["valid"]);self.assertEqual(resource["point_count"],60);self.assertEqual(resource["filename"],"station-outline.json")
            with urllib.request.urlopen(self.base+f"/api/outlines/{oid}") as response:self.assertEqual(json.load(response)["rings"][0][0],[24.0951,105.7465])
            with urllib.request.urlopen(self.base+"/api/outlines") as response:self.assertIn(oid,[x["outline_id"] for x in json.load(response)["outlines"]])
            request=urllib.request.Request(self.base+f"/api/outlines/{oid}",method="DELETE")
            with urllib.request.urlopen(request) as response:self.assertTrue(json.load(response)["deleted"])
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(self.base+f"/api/outlines/{oid}")
            self.assertEqual(error.exception.code,404)
        finally:
            if oid in outline_store.resources:outline_store.delete(oid)

    def test_invalid_upload_and_request_size_are_4xx(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.upload(b"{}")
        self.assertEqual(error.exception.code,422)
        request=urllib.request.Request(self.base+"/api/outlines",b"x"*(MAX_UPLOAD_BYTES+65537),{"Content-Type":"multipart/form-data; boundary=x"},method="POST")
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,413)


class MixedProviderTests(unittest.TestCase):
    def setUp(self):
        self.created=[]

    def tearDown(self):
        for oid in self.created:
            if oid in outline_store.resources:outline_store.delete(oid)

    def add_outline(self,points):
        resource=outline_store.create(outline_bytes(points),"test-outline.json");self.created.append(resource["outline_id"]);return resource["outline_id"]

    def receivers(self):
        return [{**x,"max_range_km":350} for x in CURRENT_RECEIVERS]

    def as_outline(self,r,oid):
        return {**r,"reception_model":"outline","outline_id":oid,"outline_filename":"test-outline.json","outline_source":"upload"}

    def test_four_outline_full_gate_matches_four_simulated_geometry(self):
        base=self.receivers();oid=self.add_outline(square(18,105,22,109));outlined=[self.as_outline(x,oid) for x in base]
        a=analyze_payload(payload(base));b=analyze_payload(payload(outlined))
        self.assertEqual(len(a["grid"]),len(b["grid"]))
        for x,y in zip(a["grid"],b["grid"]):
            self.assertEqual(x["quality"],y["quality"]);self.assertEqual(x["condition"],y["condition"]);self.assertEqual(x["predicted_p95_error_m"],y["predicted_p95_error_m"])

    def test_three_outline_one_simulated_mixed_provider(self):
        oid=self.add_outline(square(18,105,22,109));r=self.receivers();mixed=[self.as_outline(x,oid) if i<3 else x for i,x in enumerate(r)]
        result=analyze_payload(payload(mixed));self.assertGreater(result["summary"]["mlat_available_points"],0);self.assertEqual(result["summary"]["reception_source_counts"],{"simulated":1,"outline":3})
        self.assertEqual({x["provider"] for x in result["grid"][0]["reception"]},{"outline","simulated"})

    def test_outline_excludes_region_and_produces_no_mlat(self):
        oid=self.add_outline(square(19.5,106.5,20.5,107.0));r=self.receivers();r[0]=self.as_outline(r[0],oid)
        result=analyze_payload(payload(r));qualities={x["quality"] for x in result["grid"]}
        self.assertIn("NO_MLAT",qualities);self.assertTrue(any(x["quality"]!="NO_MLAT" for x in result["grid"]))

    def test_fifth_receiver_does_not_substitute_unavailable_selected_outline(self):
        oid=self.add_outline(square(10,100,11,101));r=self.receivers();r[0]=self.as_outline(r[0],oid);r.append({"id":"rx5","name":"RX5","lat":20,"lon":107,"altitude_m":30,"reception_model":"simulated","max_range_km":350,"enabled":True})
        result=analyze_payload(payload(r,selected=[x["id"] for x in r[:4]]))
        self.assertTrue(all(x["quality"]=="NO_MLAT" for x in result["grid"]))
        self.assertTrue(any(x["receiver_count"]>=4 for x in result["grid"]))
        self.assertTrue(all("does not substitute" in x["strict_subset_message"] for x in result["grid"]))

    def test_missing_outline_id_identifies_receiver(self):
        r=self.receivers();r[0]=self.as_outline(r[0],"outline-missing")
        with self.assertRaisesRegex(ValueError,"Receiver T37.*Unknown outline_id"):analyze_payload(payload(r))


class Phase2FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend=ROOT/"deployment_planner"/"frontend";cls.html=(frontend/"index.html").read_text();cls.js=(frontend/"app.js").read_text()

    def test_upload_model_metadata_and_observed_caveat(self):
        for token in ("Observed readsb outline reflects where aircraft have been received", "show-all-reception", "hide-all-reception"):
            self.assertIn(token,self.html)
        for token in ('data-model', 'data-upload', 'Uploading…', 'Parsing…', 'Status: Valid', '/api/outlines'):
            self.assertIn(token,self.js)

    def test_outline_overlay_comparison_and_deterministic_delete(self):
        for token in ('L.polygon(ring', 'show_simulated_comparison', 'Show simulated comparison circle', 'method:"DELETE"', 'r.reception_model="simulated"'):
            self.assertIn(token,self.js)

    def test_mixed_eligibility_strict_warning_and_arbitrary_count(self):
        for token in ('x.reason', 'strict_subset_message', 'countColor', 'reception_source_counts', 'selected_strict_4_common_coverage_percent'):
            self.assertIn(token,self.js)

    def test_invalid_pending_outline_disables_analysis(self):
        for token in ('state.uploading>0', '!outlineReady(r)', 'Upload a valid outline for'):
            self.assertIn(token,self.js)


if __name__=="__main__":unittest.main()
