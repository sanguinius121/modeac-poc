import threading
import unittest
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

from frontend.server import Handler
from realtime.api import cors_header


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_static_server_and_assets(self):
        for path, content_type in (("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")):
            with urllib.request.urlopen(self.base + path, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertTrue(response.read())

    def test_frontend_uses_unified_contract_and_lifecycle(self):
        source = (ROOT / "frontend/app.js").read_text()
        for endpoint in ("/api/modeac/tracks", "/api/modes/tracks", "/api/receivers", "/api/clocks", "/api/modeac/stats", "/api/modes/stats", "/health", "/ws/modeac", "/ws/modes"):
            self.assertIn(endpoint, source)
        for event in ("track_created", "track_updated", "track_stale", "track_removed"):
            self.assertIn(event, source)
        self.assertIn("setTimeout(()=>connectWebSocket(kind)", source)
        self.assertIn("QUALITY_RANK", source)
        self.assertIn('input[data-source=', source)

    def test_independent_namespaces_layers_and_cotrack_guardrails(self):
        source = (ROOT / "frontend/app.js").read_text()
        html = (ROOT / "frontend/index.html").read_text()
        for token in ("modeAcTracks", "modeSTracks", "modeAcLayer", "modeSLayer", "modeAcWsBadge", "modeSWsBadge", "HISTORY_MS", "STRONG_POINTS: 3", "STRONG_COTRACK", "phase9Diagnostics"):
            self.assertIn(token, source + html)
        self.assertIn("MODEAC_MLAT_4RX", source)
        self.assertIn("MODES_MLAT_4RX", source)
        self.assertIn("not identity", html.lower())

    def test_blind_first_and_warning_copy(self):
        combined = (ROOT / "frontend/index.html").read_text() + (ROOT / "frontend/app.js").read_text()
        self.assertNotIn("aircraft.json", combined)
        self.assertNotIn("tar1090", combined.lower())
        self.assertIn("clock quality degraded", combined.lower())
        self.assertIn("not ADS-B", combined)

    def test_cors_is_narrow(self):
        allowed = cors_header({"origin": "http://100.100.24.4:8088"})
        denied = cors_header({"origin": "http://example.invalid"})
        self.assertIn("100.100.24.4:8088", allowed)
        self.assertEqual(denied, "")


if __name__ == "__main__":
    unittest.main()
