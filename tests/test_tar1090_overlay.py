import pathlib,unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class Tar1090OverlayContractTests(unittest.TestCase):
    def setUp(self):
        self.js=(ROOT/"tar1090-overlay/poc-mlat-overlay.js").read_text()
        self.index=(ROOT/"tar1090-overlay/stage/index.html").read_text()

    def test_isolated_namespaces_and_sources(self):
        self.assertIn('window.pocModeSTracks = registries.modes',self.js)
        self.assertIn('window.pocModeAcTracks = registries.modeac',self.js)
        self.assertIn('MODES_MLAT_4RX',self.js)
        self.assertIn('MODEAC_MLAT_4RX',self.js)
        self.assertNotIn('g.planes[',self.js)
        self.assertNotIn('new PlaneObject',self.js)

    def test_measurement_age_and_bounded_history(self):
        self.assertIn('Date.parse(track.last_seen',self.js)
        self.assertIn('now - entry.measurementMs',self.js)
        self.assertIn('historyMs: 10 * 60 * 1000',self.js)
        self.assertIn('staleRemoveMs: 120 * 1000',self.js)
        self.assertIn('measurementMs < entry.measurementMs',self.js)

    def test_websocket_phase10b(self):
        self.assertIn('phase: "10B_WEBSOCKET"',self.js)
        self.assertIn('new WebSocket',self.js)
        self.assertIn('connectSocket("modes")',self.js)
        self.assertIn('connectSocket("modeac")',self.js)
        self.assertNotIn('setInterval(pollTracks, CONFIG.trackPollMs)',self.js)
        self.assertIn('state.backoffMs * 2',self.js)
        self.assertIn('measurementMs < entry.measurementMs',self.js)

    def test_minimal_index_hook(self):
        self.assertEqual(self.index.count('poc-mlat-overlay.css'),1)
        self.assertEqual(self.index.count('poc-mlat-overlay.js'),1)
        self.assertLess(self.index.index('script_b0f58f28592f8ca593d4a390cbbb6387.js'),self.index.index('poc-mlat-overlay.js'))

    def test_user_controlled_fit_does_not_auto_move_map(self):
        self.assertIn("class='poc-fit-button'",self.js)
        self.assertIn('function fitPocTracks()',self.js)
        self.assertIn('maxZoom: 9',self.js)
        self.assertNotIn('ol.extent',self.js)
        self.assertNotIn('fitPocTracks();',self.js)

    def test_markers_use_supported_svg_icon_renderer(self):
        self.assertIn('new ol.style.Icon',self.js)
        self.assertIn('MARKER_ICON[kind]',self.js)
        self.assertNotIn('RegularShape',self.js)

if __name__=="__main__":unittest.main()
