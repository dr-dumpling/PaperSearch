"""One remote-debugging connection to the user's ego, shared by backend processes.

ego asks the user to allow every new remote-debugging connection, and each
paper runs in a new backend process. The relay connects to ego once (one
approval) and serves backend processes, one at a time, on a local WebSocket
endpoint. Command ids are remapped so late replies never reach the wrong
client, and when a client leaves, the sessions it attached are detached and
auto-attach is switched off, so the next client starts clean.

The relay exits when ego closes the connection or after IDLE_EXIT_SEC without
a client. Its state file tells backends where to connect:
{"pid", "port", "upstream", "started"}.

    python -m paper_search_school.browser.ego_relay --upstream WS --state FILE
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import time
from pathlib import Path
from typing import Any

IDLE_EXIT_SEC = 2 * 3600
CLIENT_WAIT_SEC = 120
CLEANUP_TIMEOUT_SEC = 5


class Relay:
    def __init__(self, upstream_url: str, state_file: Path):
        self.upstream_url = upstream_url
        self.state_file = state_file
        self.upstream: Any = None
        self.ids = itertools.count(1)
        self.pending: dict[int, tuple[Any, Any]] = {}  # upstream id -> (client or None, client id or future)
        self.client: Any = None
        self.client_sessions: set[str] = set()
        self.free = asyncio.Event()
        self.free.set()
        self.last_activity = time.monotonic()

    async def call(self, method: str, params: dict[str, Any]) -> None:
        """A relay-owned command (cleanup); the reply is consumed here."""
        uid = next(self.ids)
        future = asyncio.get_running_loop().create_future()
        self.pending[uid] = (None, future)
        await self.upstream.send(json.dumps({"id": uid, "method": method, "params": params}))
        try:
            await asyncio.wait_for(future, CLEANUP_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            self.pending.pop(uid, None)

    async def handle(self, ws: Any) -> None:
        try:
            await asyncio.wait_for(self.free.wait(), CLIENT_WAIT_SEC)
        except asyncio.TimeoutError:
            await ws.close(1013, "relay busy")
            return
        self.free.clear()
        self.client, self.client_sessions = ws, set()
        try:
            async for raw in ws:
                self.last_activity = time.monotonic()
                message = json.loads(raw)
                if "id" in message:
                    uid = next(self.ids)
                    self.pending[uid] = (ws, message["id"])
                    message["id"] = uid
                await self.upstream.send(json.dumps(message))
        except Exception:
            pass  # a client that drops mid-message is cleaned up below
        finally:
            sessions, self.client = set(self.client_sessions), None
            for uid in [u for u, (c, _) in self.pending.items() if c is ws]:
                self.pending.pop(uid, None)
            await self.cleanup(sessions)
            self.last_activity = time.monotonic()
            self.free.set()

    async def cleanup(self, sessions: set[str]) -> None:
        for session in sessions:
            await self.call("Target.detachFromTarget", {"sessionId": session})
        await self.call("Target.setAutoAttach", {"autoAttach": False, "waitForDebuggerOnStart": False, "flatten": True})
        await self.call("Target.setDiscoverTargets", {"discover": False})

    async def route(self) -> None:
        async for raw in self.upstream:
            message = json.loads(raw)
            if "id" in message:
                client, ref = self.pending.pop(message["id"], (None, None))
                if client is None:
                    if isinstance(ref, asyncio.Future) and not ref.done():
                        ref.set_result(message)
                    continue
                if client is self.client:
                    message["id"] = ref
                    await client.send(json.dumps(message))
                continue
            method = message.get("method")
            params = message.get("params") or {}
            if method == "Target.attachedToTarget" and params.get("sessionId"):
                self.client_sessions.add(params["sessionId"])
            elif method == "Target.detachedFromTarget" and params.get("sessionId"):
                self.client_sessions.discard(params["sessionId"])
            if self.client is not None:
                try:
                    await self.client.send(raw)
                except Exception:
                    pass

    async def idle_watch(self) -> None:
        while True:
            await asyncio.sleep(60)
            if self.free.is_set() and time.monotonic() - self.last_activity > IDLE_EXIT_SEC:
                return

    async def run(self) -> None:
        import websockets

        self.upstream = await websockets.connect(self.upstream_url, max_size=None, ping_interval=None)
        server = await websockets.serve(self.handle, "127.0.0.1", 0, max_size=None, ping_interval=None)
        port = server.sockets[0].getsockname()[1]
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "port": port, "upstream": self.upstream_url,
                                   "started": time.time()}))
        os.replace(tmp, self.state_file)
        try:
            done, _ = await asyncio.wait(
                [asyncio.create_task(self.route()), asyncio.create_task(self.idle_watch())],
                return_when=asyncio.FIRST_COMPLETED)
        finally:
            server.close()
            try:
                if json.loads(self.state_file.read_text()).get("pid") == os.getpid():
                    self.state_file.unlink()
            except (OSError, ValueError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    asyncio.run(Relay(args.upstream, Path(args.state)).run())


if __name__ == "__main__":
    main()
