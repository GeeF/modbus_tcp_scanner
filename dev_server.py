"""Local Modbus TCP server seeded with predictable values, for smoke testing the TUI.

Run:  python dev_server.py
Bind: 127.0.0.1:5020

Seeded address range: 0..255
  holding/input registers: value[i] = 0x1000 + i
  coils/discrete inputs:   value[i] = i % 2

Reading past the seeded range returns Modbus exception 0x02 (Illegal Data Address),
which is useful for testing the scanner's error path.
"""

from __future__ import annotations

import asyncio
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from pymodbus.datastore import (
        ModbusDeviceContext,
        ModbusSequentialDataBlock,
        ModbusServerContext,
    )

from pymodbus.server import StartAsyncTcpServer


HOST = "127.0.0.1"
PORT = 5020
RANGE = 256


def build_context() -> ModbusServerContext:
    bits = [i % 2 for i in range(RANGE)]
    words = [(0x1000 + i) & 0xFFFF for i in range(RANGE)]
    # Legacy datastore uses 1-based starting addresses; PDU address 0 maps to index 0.
    device = ModbusDeviceContext(
        co=ModbusSequentialDataBlock(1, bits),
        di=ModbusSequentialDataBlock(1, bits),
        hr=ModbusSequentialDataBlock(1, words),
        ir=ModbusSequentialDataBlock(1, words),
    )
    return ModbusServerContext(devices=device, single=True)


async def main() -> None:
    print(f"Modbus TCP dev server listening on {HOST}:{PORT}")
    print(f"Seeded address range: 0..{RANGE - 1}")
    print("  holding/input registers: value[i] = 0x1000 + i")
    print("  coils/discrete inputs:   value[i] = i % 2")
    print("  reads beyond address 255 return Exception 0x02 (Illegal Data Address)")
    await StartAsyncTcpServer(context=build_context(), address=(HOST, PORT))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
