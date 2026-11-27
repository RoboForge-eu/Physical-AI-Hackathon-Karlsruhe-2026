"""Offline-Tests fuer stream_livekit.py (ohne Netz, ohne LiveKit-Server)."""
import base64, json, tempfile, unittest
from pathlib import Path
import stream_livekit as S

CFG = {"url": "wss://test.livekit.cloud", "api_key": "APItest", "api_secret": "s" * 40, "room": "roboforge"}


def claims(jwt):
    body = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


class ConfigTests(unittest.TestCase):
    def write(self, data):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "livekit.json"
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return p

    def test_missing_file(self):
        cfg, why = S.load_config(Path(tempfile.gettempdir()) / "gibt-es-nicht.json")
        self.assertIsNone(cfg)
        self.assertIn("fehlt", why)

    def test_template_values_are_rejected(self):
        example = (S.HERE / "livekit.example.json").read_text(encoding="utf-8")
        cfg, why = S.load_config(self.write(example))
        self.assertIsNone(cfg)

    def test_valid_config_gets_defaults(self):
        cfg, why = S.load_config(self.write(CFG))
        self.assertIsNone(why)
        self.assertEqual(cfg["fps"], 15)
        self.assertEqual(cfg["room"], "roboforge")


class TokenTests(unittest.TestCase):
    def test_robot_may_publish_only(self):
        c = claims(S.make_token(S.DEFAULTS | CFG, "roboter-pc", publish=True))
        self.assertEqual(c["sub"], "roboter-pc")
        self.assertTrue(c["video"]["canPublish"])
        self.assertFalse(c["video"]["canSubscribe"])
        self.assertEqual(c["video"]["room"], "roboforge")

    def test_viewer_may_only_watch_and_secret_never_appears(self):
        link = S.viewer_link(S.DEFAULTS | CFG)
        self.assertNotIn(CFG["api_secret"], link)
        self.assertNotIn("?", link.split("#")[0][-20:])           # nichts in der Abfrage, alles nach '#'
        token = link.split("token=")[1]
        c = claims(token)
        self.assertFalse(c["video"]["canPublish"])
        self.assertTrue(c["video"]["canSubscribe"])

    def test_only_operator_tokens_may_send_control_data(self):
        viewer = claims(S.viewer_link(S.DEFAULTS | CFG).split("token=")[1])
        self.assertFalse(viewer["video"].get("canPublishData", False))
        robot_video = claims(S.make_token(S.DEFAULTS | CFG, "roboter-pc", publish=True))
        self.assertFalse(robot_video["video"].get("canPublishData", False))
        operator = claims(S.make_token(S.DEFAULTS | CFG, "bediener", publish=False, data=True))
        self.assertTrue(operator["video"]["canPublishData"])
        self.assertFalse(operator["video"]["canPublish"])

    def test_placeholder_frame(self):
        img = S.placeholder(640, 360, "Setup 1 · Arm: Kamera fehlt")
        self.assertEqual(img.shape, (360, 640, 3))


if __name__ == "__main__":
    unittest.main()
