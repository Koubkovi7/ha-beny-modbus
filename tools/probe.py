"""Read-only BENY probe. No register writes, retries, or charging commands."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "beny_modbus"))
from library.device import BenyDevice
from library.protocol import BenyError, ModbusClient


async def main(args):
    client = ModbusClient(args.host, args.port, args.unit, args.transport)
    device = BenyDevice(client)
    result = {"host": args.host, "port": args.port, "transport": args.transport,
              "unit": args.unit, "writes": 0}
    try:
        result["identity"] = asdict(await device.identify())
        result["snapshot"] = asdict(await device.poll())
        try:
            result["watchdog_seconds"] = await device.read_watchdog()
        except BenyError as err:
            result["watchdog_error"] = str(err)
        result["ok"] = True
    except BenyError as err:
        result.update(ok=False, error=str(err))
    finally:
        await client.close()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--unit", type=int, default=1)
    parser.add_argument("--transport", choices=("tcp", "rtu_over_tcp"), default="tcp")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
