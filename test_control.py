"""Tests: wer darf steuern (remote_control.ControlDesk)."""
import unittest
from remote_control import ControlDesk


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.d = ControlDesk(max_min=30)
        for c in ("a", "b", "c"):
            self.d.join(c, device=f"dev-{c}", name=f"PC {c}")

    def test_first_claim_wins_and_keeps(self):
        self.assertTrue(self.d.claim("a", 10, 0))
        self.assertFalse(self.d.claim("b", 10, 1))
        self.assertEqual(self.d.view("b", 1)["role"], "spectator")
        self.assertEqual(self.d.view("a", 60)["left_s"], 540)

    def test_limit_and_expiry_to_queue(self):
        self.d.claim("a", 99, 0)                           # max 30 min
        self.d.enqueue("b", 5)
        self.assertEqual(self.d.view("b", 0)["wait_s"], 1800)
        self.d.tick(1800)
        self.assertEqual(self.d.holder, "b")
        kinds = [m["kind"] for c, m in self.d.pop_notices() if c == "a"]
        self.assertIn("expired", kinds)
        self.assertEqual(self.d.view("b", 1800)["left_s"], 300)

    def test_request_accept_and_decline(self):
        self.d.claim("a", 10, 0)
        self.d.request("b")
        self.assertEqual(self.d.view("a", 0)["request_from"], "PC b")
        self.d.answer("a", False, 1)
        self.assertEqual(self.d.holder, "a")
        self.d.request("c")
        self.d.answer("a", True, 2)
        self.assertEqual(self.d.holder, "c")

    def test_release_kick_extend_remember(self):
        self.d.claim("a", 10, 0)
        self.d.enqueue("b")
        self.d.release("a", 5)
        self.assertEqual(self.d.holder, "b")
        self.d.kick("b", 6)
        self.assertIsNone(self.d.holder)
        self.assertIn("kicked", [m["kind"] for c, m in self.d.pop_notices() if c == "b"])
        self.assertTrue(self.d.remember("c", 120))
        self.d.claim("c", 90, 10)
        self.assertEqual(self.d.view("c", 10)["left_s"], 5400)
        self.d.ask_extend("c")
        self.assertTrue(self.d.overview(10)["extend_wanted"])
        self.d.extend(15)
        self.assertEqual(self.d.view("c", 10)["left_s"], 6300)

    def test_holder_leaves(self):
        self.d.claim("a", 10, 0)
        self.d.enqueue("b")
        self.d.leave("a", 3)
        self.assertEqual(self.d.holder, "b")


if __name__ == "__main__":
    unittest.main()


class LaneServerTests(unittest.TestCase):
    def test_second_device_gets_free_arm_and_can_switch(self):
        import asyncio, json
        from remote_server import Server
        srv = Server(log=lambda *_: None)
        srv.set_arms({"follower": ("Setup 1", True, True), "follower2": ("Setup 2", True, True)})
        out = {}

        def sender(cid):
            async def send(raw, msg):
                out.setdefault(cid, []).append(msg)
            return send

        async def run():
            for c in ("a", "b"):
                srv.add_client(c, sender(c), "test")
            await srv.receive("a", json.dumps({"t": "hello", "v": 1, "device": "d-a", "name": "PC A"}))
            await srv.receive("a", json.dumps({"t": "claim", "min": 10}))
            await srv.receive("b", json.dumps({"t": "hello", "v": 1, "device": "d-b", "name": "PC B"}))
            self.assertEqual(srv.lanes["follower"].desk.holder, "a")
            self.assertEqual(srv.lane_of("b").key, "follower2")          # freier Arm automatisch
            await srv.receive("b", json.dumps({"t": "claim", "min": 5}))
            self.assertEqual(srv.lanes["follower2"].desk.holder, "b")
            await srv.receive("b", json.dumps({"t": "select", "arm": "follower"}))
            self.assertIsNone(srv.lanes["follower2"].desk.holder)       # beim Wechsel abgegeben
            await srv.receive("b", json.dumps({"t": "claim", "min": 5}))
            self.assertEqual(srv.lanes["follower"].desk.holder, "a")     # belegt: bleibt bei a
            srv.remove_client("a")
            self.assertIsNone(srv.lanes["follower"].desk.holder)
        asyncio.run(run())
