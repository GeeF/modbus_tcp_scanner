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

from pymodbus.server import StartAsyncTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice


HOST = "127.0.0.1"
PORT = 5020
RANGE = 256


def build_device() -> SimDevice:
    bits = [bool(i % 2) for i in range(RANGE)]
    words = [(0x1000 + i) & 0xFFFF for i in range(RANGE)]
    # Passing values as a list seeds exactly len(values) registers/bits at `address`.
    # NOTE: do not also pass count=; SimData treats count as a multiplier on the list,
    # which would inflate the seeded range and cause out-of-range reads to wrap
    # instead of returning Exception 0x02.
    return SimDevice(
        id=1,
        simdata=(
            [SimData(0, values=bits, datatype=DataType.BITS)],
            [SimData(0, values=bits, datatype=DataType.BITS)],
            [SimData(0, values=words, datatype=DataType.REGISTERS)],
            [SimData(0, values=words, datatype=DataType.REGISTERS)],
        ),
    )


async def main() -> None:
    print(f"Modbus TCP dev server listening on {HOST}:{PORT}")
    print(f"Seeded address range: 0..{RANGE - 1}")
    print("  holding/input registers: value[i] = 0x1000 + i")
    print("  coils/discrete inputs:   value[i] = i % 2")
    print("  reads beyond address 255 return Exception 0x02 (Illegal Data Address)")
    await StartAsyncTcpServer(context=build_device(), address=(HOST, PORT))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
