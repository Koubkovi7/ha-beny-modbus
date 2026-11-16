"""Run wire-format tests with in-memory streams, without opening any sockets.

The regular suite uses localhost TCP sockets. This optional harness exercises
the same client/server frame parsing in restricted runners where even asyncio's
internal Windows socketpair is unavailable. It does not validate OS networking,
Home Assistant, or real hardware. No production code is patched or shipped
inside custom_components by this harness.
"""
import asyncio
import selectors
import sys
import time
import unittest
from unittest.mock import patch

import test_beny


class NoIOSelector(selectors.BaseSelector):
    def register(self, *args, **kwargs):
        raise RuntimeError("Real I/O is not allowed in the memory test harness")

    def unregister(self, *args, **kwargs):
        raise RuntimeError("Real I/O is not allowed in the memory test harness")

    def select(self, timeout=None):
        if timeout:
            time.sleep(min(timeout, 0.05))
        return []

    def get_map(self):
        return {}


class MemoryLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        super().__init__(selector=NoIOSelector())

    def _make_self_pipe(self):
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        pass


class MemoryWriter:
    def __init__(self, peer):
        self.peer = peer
        self.closed = False

    def write(self, data):
        if self.closed:
            raise ConnectionError("Closed memory stream")
        self.peer.feed_data(data)

    async def drain(self):
        await asyncio.sleep(0)

    def is_closing(self):
        return self.closed

    def close(self):
        if not self.closed:
            self.closed = True
            self.peer.feed_eof()

    async def wait_closed(self):
        await asyncio.sleep(0)


active_simulator = None


async def open_simulator(sim):
    global active_simulator
    active_simulator = sim
    return 1


async def close_simulator(sim):
    for writer in tuple(sim.writers):
        writer.close()
    for task in tuple(sim.tasks):
        task.cancel()
    await asyncio.gather(*tuple(sim.tasks), return_exceptions=True)


async def connect(*args, **kwargs):
    incoming, outgoing = asyncio.StreamReader(), asyncio.StreamReader()
    client_writer, server_writer = MemoryWriter(incoming), MemoryWriter(outgoing)
    asyncio.create_task(active_simulator.handle(incoming, server_writer))
    return outgoing, client_writer


def setup_runner(case):
    case._asyncioRunner = asyncio.Runner(debug=True, loop_factory=MemoryLoop)


if __name__ == "__main__":
    with (
        patch.object(test_beny.Simulator, "open", open_simulator),
        patch.object(test_beny.Simulator, "close", close_simulator),
        patch.object(asyncio, "open_connection", connect),
        patch.object(unittest.IsolatedAsyncioTestCase, "_setupAsyncioRunner", setup_runner),
    ):
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_beny)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(not result.wasSuccessful())
