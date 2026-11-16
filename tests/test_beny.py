"""Protocol and control tests against a local TCP/RTU simulator (no HA required)."""
import asyncio
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "beny_modbus"))
from library.protocol import BenyError, ModbusClient, ModbusException, WriteUncertain, crc16
from library.device import BenyDevice, CommandRejected


class Simulator:
    def __init__(self, transport="rtu_over_tcp"):
        self.transport = transport
        model = b"BCP-AT2N-L".ljust(20, b"\0")
        self.inputs = {0: 3, 11: 128, 12: 1}
        self.inputs.update({i + 1: int.from_bytes(model[2*i:2*i+2], "big") for i in range(10)})
        self.inputs.update(dict(zip(range(0x100, 0x10A),
                                    [123, 2301, 2312, 2299, 160, 0, 159, 0, 1, 16])))
        self.holding = {0x200: 16, 0x201: 0, 0x203: 32, 0x205: 10}
        self.writes, self.requests = [], []
        self.tasks, self.writers = set(), set()
        self.drop_ack = self.bad_ack = self.reject_start = False
        self.bad_crc = self.bad_tid = self.bad_unit = self.short_read = False
        self.fragment = False
        self.delay = 0
        self.disconnect_on_read = False
        self.disconnect_reads = 0
        self.drop_read_responses = 0
        self.drop_read_address = None
        self.drop_write_response = False
        self.drop_reads_after_write = 0
        self.connections = 0

    async def open(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        for writer in tuple(self.writers):
            writer.close()
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        self.connections += 1
        try:
            while True:
                if self.transport == "tcp":
                    header = await reader.readexactly(7)
                    tid, _, length, unit = struct.unpack(">HHHB", header)
                    pdu = await reader.readexactly(length - 1)
                else:
                    unit, fn = await reader.readexactly(2)
                    tail = await reader.readexactly(6 if fn in (3, 4) else 9)
                    frame = bytes([unit, fn]) + tail
                    assert crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")
                    pdu = frame[1:-2]
                fn, address, count = struct.unpack(">BHH", pdu[:5])
                self.requests.append((fn, address, count))
                if self.delay:
                    await asyncio.sleep(self.delay)
                if fn in (3, 4):
                    if self.disconnect_on_read or self.disconnect_reads:
                        self.disconnect_reads = max(0, self.disconnect_reads - 1)
                        return
                    if (self.drop_read_responses and
                            self.drop_read_address in (None, address)):
                        self.drop_read_responses -= 1
                        continue
                    registers = self.holding if fn == 3 else self.inputs
                    if any(address + i not in registers for i in range(count)):
                        response = bytes([fn | 0x80, 2])
                    else:
                        values = [registers[address+i] for i in range(count)]
                        if self.short_read:
                            self.short_read = False
                            values = values + [0]
                        response = bytes([fn, 2 * len(values)]) + struct.pack(f">{len(values)}H", *values)
                elif fn == 16:
                    assert count == 1 and pdu[5] == 2
                    value = int.from_bytes(pdu[6:8], "big")
                    self.writes.append((address, value))
                    if self.reject_start and (address, value) == (0x201, 1):
                        response = bytes([0x90, 3])
                    else:
                        self.holding[address] = value
                        self.drop_read_responses += self.drop_reads_after_write
                        self.drop_reads_after_write = 0
                        if self.drop_write_response:
                            continue
                        response = struct.pack(">BHH", 16, address + int(self.bad_ack), 1)
                        self.bad_ack = False
                        if self.drop_ack:
                            self.drop_ack = False
                            return
                else:
                    response = bytes([fn | 0x80, 1])
                if self.bad_unit:
                    unit += 1
                    self.bad_unit = False
                if self.transport == "tcp":
                    output = struct.pack(">HHHB", tid + int(self.bad_tid), 0, len(response)+1, unit) + response
                    self.bad_tid = False
                else:
                    output = bytes([unit]) + response
                    output += struct.pack("<H", crc16(output))
                    if self.bad_crc:
                        output = output[:-1] + bytes([output[-1] ^ 0xFF])
                        self.bad_crc = False
                if self.fragment:
                    for byte in output:
                        writer.write(bytes([byte]))
                        await writer.drain()
                        await asyncio.sleep(0)
                else:
                    writer.write(output)
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.tasks.discard(task)
            self.writers.discard(writer)


class CrcTests(unittest.TestCase):
    def test_manufacturer_vectors(self):
        for frame in ("01040100000931f0", "011002000001020010845c", "0110020100010200014581"):
            data = bytes.fromhex(frame)
            self.assertEqual(crc16(data[:-2]), int.from_bytes(data[-2:], "little"))


class DeviceTests:
    transport = "rtu_over_tcp"

    async def asyncSetUp(self):
        self.sim = Simulator(self.transport)
        port = await self.sim.open()
        self.client = ModbusClient("127.0.0.1", port, transport=self.transport, gap=0, timeout=0.2)
        self.now = 100.0
        self.device = BenyDevice(self.client, max_current=16, clock=lambda: self.now)

    async def asyncTearDown(self):
        await self.client.close()
        await self.sim.close()

    async def test_identify_and_scaling(self):
        identity = await self.device.identify()
        self.assertEqual((identity.model, identity.phases), ("BCP-AT2N-L", 3))
        data = await self.device.poll()
        self.assertEqual(data.energy_kwh, 12.3)
        self.assertEqual(data.voltages, (230.1, 231.2, 229.9))
        self.assertEqual(data.currents, (16, 0, 15.9))
        self.assertFalse(self.sim.writes)

    async def test_connection_refused_reports_stage_and_register(self):
        with patch("asyncio.open_connection", side_effect=ConnectionRefusedError("test refused")):
            with self.assertRaisesRegex(BenyError, r"FC04 register 0x0000.*opening TCP connection.*ConnectionRefusedError"):
                await self.device.identify()
        self.assertFalse(self.sim.requests)
        self.assertFalse(self.sim.writes)

    async def test_connect_timeout_is_distinct_from_response_timeout(self):
        async def slow_connect(*args, **kwargs):
            await asyncio.sleep(10)
        self.client.timeout = 0.01
        with patch("asyncio.open_connection", slow_connect):
            with self.assertRaisesRegex(BenyError, r"FC04 register 0x0000.*timeout.*opening TCP connection"):
                await self.device.identify()
        self.assertFalse(self.sim.requests)
        self.assertIsNone(self.client._writer)

    async def test_response_timeout_stops_after_two_attempts(self):
        self.sim.delay = 0.1
        self.client.timeout = 0.01
        with self.assertRaisesRegex(BenyError, r"FC04 register 0x0000.*timeout.*waiting for Modbus response.*2 attempts"):
            await self.device.identify()
        self.assertEqual(self.sim.requests, [(4, 0, 1)] * 2)
        self.assertEqual(self.sim.connections, 2)
        self.assertFalse(self.sim.writes)
        self.assertIsNone(self.client._writer)

    async def test_modbus_exception_preserves_code_and_register(self):
        del self.sim.inputs[0x101]
        with self.assertRaises(ModbusException) as error:
            await self.client.read(4, 0x101)
        self.assertEqual((error.exception.function, error.exception.code, error.exception.address), (4, 2, 0x101))
        self.assertIn("register 0x0101: exception 0x02", str(error.exception))
        self.assertEqual(self.sim.requests, [(4, 0x101, 1)])
        self.assertEqual(await self.client.read(4, 0x100), [123])
        self.assertFalse(self.sim.writes)

    async def test_closed_response_stops_after_two_attempts(self):
        self.sim.disconnect_on_read = True
        with self.assertRaisesRegex(BenyError, r"FC04 register 0x0000.*peer closed connection.*waiting for Modbus response.*2 attempts"):
            await self.device.identify()
        self.assertEqual(self.sim.requests, [(4, 0, 1)] * 2)
        self.assertEqual(self.sim.connections, 2)
        self.assertFalse(self.sim.writes)
        self.assertIsNone(self.client._writer)

    async def test_dropped_read_recovers_on_new_connection(self):
        self.client.timeout = 0.03
        expected = []
        for function, address, value in ((4, 0x103, 2299), (3, 0x200, 16)):
            self.sim.drop_read_responses = 1
            self.assertEqual(await self.client.read(function, address), [value])
            expected.extend([(function, address, 1)] * 2)
        self.assertEqual(self.sim.requests, expected)
        self.assertEqual(self.sim.connections, 3)
        self.assertFalse(self.sim.writes)

    async def test_closed_read_recovers_on_new_connection(self):
        self.sim.disconnect_reads = 1
        self.assertEqual(await self.client.read(4, 0), [3])
        self.assertEqual(self.sim.requests, [(4, 0, 1)] * 2)
        self.assertEqual(self.sim.connections, 2)
        self.assertFalse(self.sim.writes)

    async def test_setup_retries_only_the_failed_register(self):
        self.client.timeout = 0.03
        self.sim.drop_read_responses = 1
        self.sim.drop_read_address = 0x103
        identity = await self.device.identify()
        snapshot = await self.device.poll()
        self.assertEqual(identity.model, "BCP-AT2N-L")
        self.assertEqual(snapshot.voltages, (230.1, 231.2, 229.9))
        self.assertEqual(len(self.sim.requests), 27)
        self.assertEqual(self.sim.requests.count((4, 0x103, 1)), 2)
        self.assertEqual(self.sim.requests.count((4, 0, 1)), 1)
        self.assertFalse(self.sim.writes)

    async def test_failed_poll_does_not_publish_partial_snapshot(self):
        original = await self.device.poll()
        self.sim.inputs[0x100] = 999
        self.client.timeout = 0.03
        self.sim.drop_read_responses = 2
        self.sim.drop_read_address = 0x103
        with self.assertRaisesRegex(BenyError, "2 attempts"):
            await self.device.poll()
        self.assertIs(self.device.snapshot, original)
        self.assertFalse(self.sim.writes)

    async def test_cancelled_read_does_not_retry(self):
        self.sim.drop_read_responses = 10
        task = asyncio.create_task(self.client.read(4, 0))
        try:
            async with asyncio.timeout(1):
                while not self.sim.requests:
                    await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(self.sim.requests, [(4, 0, 1)])
            self.assertIsNone(self.client._writer)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_write_timeout_never_repeats_write(self):
        self.client.timeout = 0.03
        self.sim.drop_write_response = True
        with self.assertRaises(WriteUncertain):
            await self.client.write(0x201, 1)
        self.assertEqual(self.sim.requests, [(16, 0x201, 1)])
        self.assertEqual(self.sim.writes, [(0x201, 1)])
        self.assertEqual(self.sim.connections, 1)
        self.assertEqual(await self.client.read(3, 0x201), [1])
        self.assertEqual(self.sim.writes, [(0x201, 1)])

    async def test_readback_retry_does_not_repeat_start(self):
        self.client.timeout = 0.03
        self.sim.drop_ack = True
        self.sim.drop_reads_after_write = 1
        await self.device.start()
        self.assertEqual(self.sim.writes, [(0x201, 1)])
        self.assertEqual(self.sim.requests.count((3, 0x201, 1)), 3)
        self.assertEqual(self.sim.connections, 3)

    async def test_retry_still_rejects_wrong_response(self):
        self.client.timeout = 0.03
        self.sim.drop_read_responses = 1
        self.sim.bad_unit = True
        with self.assertRaises(BenyError):
            await self.client.read(4, 0)
        self.assertEqual(self.sim.requests, [(4, 0, 1)] * 2)
        self.assertEqual(self.sim.connections, 2)
        self.assertFalse(self.sim.writes)

    async def test_unknown_state_reports_actual_values(self):
        self.sim.holding[0x201] = 99
        self.sim.inputs[0x108] = 7
        with self.assertRaisesRegex(BenyError, r"authorization 0x0201=99, connector 0x0108=7"):
            await self.device.poll()
        self.assertFalse(self.sim.writes)

    async def test_read_only_setup_poll_and_watchdog(self):
        await self.device.identify()
        await self.device.read_watchdog()
        for _ in range(3):
            await self.device.poll()
        self.assertFalse(self.sim.writes)
        self.assertTrue(all(count == 1 and fn in (3, 4) for fn, _, count in self.sim.requests))

    async def test_duplicate_concurrent_starts_write_once(self):
        await asyncio.gather(*(self.device.start() for _ in range(25)))
        self.assertEqual(self.sim.writes, [(0x201, 1)])

    async def test_authorized_idle_does_not_restart(self):
        self.sim.holding[0x201] = 1
        self.assertFalse(await self.device.start())
        self.assertFalse(self.sim.writes)

    async def test_current_uses_only_volatile_register_and_deduplicates(self):
        await self.device.set_current(10)
        self.assertFalse(await self.device.set_current(10))
        self.assertEqual(self.sim.writes, [(0x200, 10)])

    async def test_start_applies_configured_ceiling_first(self):
        self.sim.holding[0x200] = 32
        await self.device.start()
        self.assertEqual(self.sim.writes, [(0x200, 16), (0x201, 1)])

    async def test_default_ceiling_six_amps(self):
        await BenyDevice(self.client).start()
        self.assertEqual(self.sim.writes, [(0x200, 6), (0x201, 1)])

    async def test_start_current_below_minimum(self):
        self.sim.holding[0x200] = 0
        await self.device.start()
        self.assertEqual(self.sim.writes, [(0x200, 6), (0x201, 1)])

    async def test_respects_permanent_limit(self):
        self.sim.holding[0x203] = 10
        with self.assertRaises(CommandRejected):
            await self.device.set_current(11)
        await self.device.start()
        self.assertEqual(self.sim.writes, [(0x200, 10), (0x201, 1)])

    async def test_rejects_invalid_current(self):
        for value in (True, "10", float("inf"), float("nan"), 6.5, 0, 5, 17):
            with self.subTest(value=value), self.assertRaises(CommandRejected):
                await self.device.set_current(value)
        self.assertFalse(self.sim.writes)

    async def test_invalid_permanent_limit_blocks_write(self):
        self.sim.holding[0x203] = 65535
        with self.assertRaises(CommandRejected):
            await self.device.start()
        with self.assertRaises(CommandRejected):
            await self.device.set_current(6)
        self.assertFalse(self.sim.writes)

    async def test_fault_blocks_start_but_allows_stop(self):
        self.sim.inputs[0x107] = 1 << 11
        with self.assertRaises(CommandRejected):
            await self.device.start()
        self.sim.holding[0x201] = 1
        await self.device.stop()
        self.assertEqual(self.sim.writes, [(0x201, 0)])

    async def test_unknown_authorization_blocks_start(self):
        self.sim.holding[0x201] = 99
        with self.assertRaises(CommandRejected):
            await self.device.start()
        self.assertFalse(self.sim.writes)

    async def test_charging_without_authorization_blocks_start(self):
        self.sim.inputs[0x108] = 2
        with self.assertRaises(CommandRejected):
            await self.device.start()
        self.assertFalse(self.sim.writes)

    async def test_stop_immediate_but_restart_has_cooldown(self):
        await self.device.start()
        await self.device.stop()
        with self.assertRaises(CommandRejected):
            await self.device.start()
        self.now += 31
        await self.device.start()
        self.assertEqual(self.sim.writes, [(0x201, 1), (0x201, 0), (0x201, 1)])

    async def test_repeated_stop_noop(self):
        await self.device.stop()
        await self.device.stop()
        self.assertFalse(self.sim.writes)

    async def test_lost_ack_readback_without_write_retry(self):
        self.sim.drop_ack = True
        await self.device.start()
        self.assertEqual(self.sim.writes, [(0x201, 1)])
        self.assertEqual(self.sim.connections, 2)

    async def test_bad_ack_readback_without_write_retry(self):
        self.sim.bad_ack = True
        await self.device.start()
        self.assertEqual(self.sim.writes, [(0x201, 1)])

    async def test_rejected_start_has_cooldown(self):
        self.sim.reject_start = True
        with self.assertRaises(ModbusException):
            await self.device.start()
        with self.assertRaises(CommandRejected):
            await self.device.start()
        self.assertEqual(self.sim.writes, [(0x201, 1)])

    async def test_control_disabled_never_writes(self):
        self.device.control_enabled = False
        for action in (self.device.start, self.device.stop, lambda: self.device.set_current(6)):
            with self.assertRaises(CommandRejected):
                await action()
        self.assertFalse(self.sim.writes)

    async def test_missing_optional_registers(self):
        del self.sim.inputs[0x109]
        del self.sim.holding[0x205]
        self.assertIsNone(await self.device.read_watchdog())
        self.assertIsNone((await self.device.poll()).allowed_current)
        self.sim.requests.clear()
        await self.device.poll()
        self.assertNotIn((4, 0x109, 1), self.sim.requests)

    async def test_missing_mandatory_register_fails(self):
        del self.sim.inputs[0x107]
        with self.assertRaises(ModbusException):
            await self.device.poll()

    async def test_unknown_connector_fails(self):
        self.sim.inputs[0x108] = 99
        with self.assertRaises(BenyError):
            await self.device.poll()

    async def test_wrong_unit_rejected_then_reconnect(self):
        self.sim.bad_unit = True
        with self.assertRaises(BenyError):
            await self.client.read(4, 0)
        self.assertEqual(await self.client.read(4, 0), [3])
        self.assertEqual(self.sim.connections, 2)

    async def test_fragmented_reply(self):
        self.sim.fragment = True
        self.assertEqual(await self.client.read(4, 0), [3])
        await self.device.set_current(6)
        self.assertEqual(self.sim.writes, [(0x200, 6)])

    async def test_unexpected_register_count(self):
        self.sim.short_read = True
        with self.assertRaises(BenyError):
            await self.client.read(4, 0)

    async def test_bounded_timeout(self):
        self.sim.delay = 2
        async with asyncio.timeout(1):
            with self.assertRaises(BenyError):
                await self.client.read(4, 0)

    async def test_serialized_poll_current_start(self):
        await asyncio.gather(self.device.poll(), self.device.set_current(10), self.device.start())
        self.assertEqual(self.sim.writes, [(0x200, 10), (0x201, 1)])
        self.assertEqual(self.sim.connections, 1)

    async def test_reject_other_device(self):
        self.sim.inputs[0] = 13
        with self.assertRaises(CommandRejected):
            await self.device.identify()
        self.assertFalse(self.sim.writes)


class RtuTests(DeviceTests, unittest.IsolatedAsyncioTestCase):
    async def test_bad_crc_rejected(self):
        self.sim.bad_crc = True
        with self.assertRaises(BenyError):
            await self.client.read(4, 0)
        self.assertEqual(await self.client.read(4, 0), [3])


class TcpTests(DeviceTests, unittest.IsolatedAsyncioTestCase):
    transport = "tcp"

    async def test_wrong_transaction_rejected(self):
        self.sim.bad_tid = True
        with self.assertRaises(BenyError):
            await self.client.read(4, 0)


if __name__ == "__main__":
    unittest.main()
