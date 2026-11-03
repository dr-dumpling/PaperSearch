"""The ego relay: one upstream connection, remapped ids, clean hand-over between clients."""
import asyncio
import json
import unittest
from pathlib import Path
import tempfile

import websockets

from paper_search_carsi.browser.ego_relay import Relay


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []  # what the fake browser got

        async def browser(ws):
            async for raw in ws:
                message = json.loads(raw)
                self.received.append(message)
                if message.get("method") == "Target.setAutoAttach" and message["params"]["autoAttach"]:
                    await ws.send(json.dumps({"method": "Target.attachedToTarget",
                                              "params": {"sessionId": "S1", "targetInfo": {}}}))
                await ws.send(json.dumps({"id": message["id"], "result": {"echo": message.get("method")}}))

        self.server = await websockets.serve(browser, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.state = Path(tempfile.mkdtemp()) / "ego-relay.json"
        self.relay = Relay(f"ws://127.0.0.1:{port}/devtools/browser/x", self.state)
        self.task = asyncio.create_task(self.relay.run())
        for _ in range(50):
            if self.state.exists():
                break
            await asyncio.sleep(0.05)
        self.endpoint = f"ws://127.0.0.1:{json.loads(self.state.read_text())['port']}/devtools/browser/relay"

    async def asyncTearDown(self):
        self.task.cancel()
        self.server.close()

    async def test_ids_are_remapped_events_forwarded_and_sessions_cleaned_up(self):
        async with websockets.connect(self.endpoint) as client:
            await client.send(json.dumps({"id": 1, "method": "Target.setAutoAttach",
                                          "params": {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}}))
            first = json.loads(await client.recv())
            second = json.loads(await client.recv())
        self.assertEqual(first["method"], "Target.attachedToTarget")
        self.assertEqual(second, {"id": 1, "result": {"echo": "Target.setAutoAttach"}})
        for _ in range(50):
            if any(m.get("method") == "Target.setDiscoverTargets" for m in self.received):
                break
            await asyncio.sleep(0.05)
        methods = [m["method"] for m in self.received]
        self.assertEqual(methods, ["Target.setAutoAttach", "Target.detachFromTarget",
                                   "Target.setAutoAttach", "Target.setDiscoverTargets"])
        self.assertEqual(self.received[1]["params"], {"sessionId": "S1"})
        self.assertEqual(len({m["id"] for m in self.received}), 4)  # upstream ids never reused

    async def test_second_client_reuses_the_same_upstream_connection(self):
        for _ in range(2):
            async with websockets.connect(self.endpoint) as client:
                await client.send(json.dumps({"id": 1, "method": "Browser.getVersion"}))
                reply = json.loads(await client.recv())
                self.assertEqual(reply, {"id": 1, "result": {"echo": "Browser.getVersion"}})
        self.assertEqual(json.loads(self.state.read_text())["upstream"], self.relay.upstream_url)


if __name__ == "__main__":
    unittest.main()
