"""Async Modbus TCP scanner. UI-agnostic — produces ScanResult records."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from pymodbus.client import AsyncModbusTcpClient


MODBUS_EXCEPTIONS: dict[int, str] = {
    0x01: "Illegal Function",
    0x02: "Illegal Data Address",
    0x03: "Illegal Data Value",
    0x04: "Server Device Failure",
    0x05: "Acknowledge",
    0x06: "Server Device Busy",
    0x08: "Memory Parity Error",
    0x0A: "Gateway Path Unavailable",
    0x0B: "Gateway Target Device Failed to Respond",
}

# Modbus protocol caps on count per request.
MAX_COUNT_BITS = 2000      # FC1, FC2
MAX_COUNT_WORDS = 125      # FC3, FC4

BIT_FUNCTIONS = {0x01, 0x02}
WORD_FUNCTIONS = {0x03, 0x04}


@dataclass
class ScanResult:
    address: int
    count: int
    function_code: int
    values: list[int] | None
    ok: bool
    status: str


def max_count_for(function_code: int) -> int:
    if function_code in BIT_FUNCTIONS:
        return MAX_COUNT_BITS
    if function_code in WORD_FUNCTIONS:
        return MAX_COUNT_WORDS
    raise ValueError(f"Unsupported function code: 0x{function_code:02X}")


async def scan(
    host: str,
    port: int,
    unit_id: int,
    function_code: int,
    start: int,
    end: int,
    count: int,
) -> AsyncIterator[ScanResult]:
    """Walk [start, end] in steps of `count`, yielding one ScanResult per read."""
    if function_code not in BIT_FUNCTIONS | WORD_FUNCTIONS:
        raise ValueError(f"Unsupported function code: 0x{function_code:02X}")
    if count < 1:
        raise ValueError("count must be >= 1")
    if count > max_count_for(function_code):
        raise ValueError(
            f"count {count} exceeds Modbus max {max_count_for(function_code)} "
            f"for FC 0x{function_code:02X}"
        )
    if end < start:
        raise ValueError("end address must be >= start address")

    client = AsyncModbusTcpClient(host, port=port)
    try:
        try:
            connected = await client.connect()
        except Exception as exc:
            yield ScanResult(
                address=start, count=count, function_code=function_code,
                values=None, ok=False, status=f"Connection failed: {exc}",
            )
            return
        if not connected:
            yield ScanResult(
                address=start, count=count, function_code=function_code,
                values=None, ok=False, status=f"Connection failed: {host}:{port}",
            )
            return

        addr = start
        while addr <= end:
            this_count = min(count, end - addr + 1)
            yield await _read_one(client, function_code, addr, this_count, unit_id)
            addr += count
    finally:
        client.close()


async def _read_one(
    client: AsyncModbusTcpClient,
    function_code: int,
    address: int,
    count: int,
    unit_id: int,
) -> ScanResult:
    reader = {
        0x01: client.read_coils,
        0x02: client.read_discrete_inputs,
        0x03: client.read_holding_registers,
        0x04: client.read_input_registers,
    }[function_code]

    try:
        response = await reader(address, count=count, device_id=unit_id)
    except Exception as exc:
        return ScanResult(
            address=address, count=count, function_code=function_code,
            values=None, ok=False, status=f"Transport error: {exc}",
        )

    if response is None:
        return ScanResult(
            address=address, count=count, function_code=function_code,
            values=None, ok=False, status="No response",
        )

    if response.isError():
        code = getattr(response, "exception_code", 0)
        name = MODBUS_EXCEPTIONS.get(code, "Unknown")
        return ScanResult(
            address=address, count=count, function_code=function_code,
            values=None, ok=False,
            status=f"Exception 0x{code:02X} ({name})",
        )

    if function_code in BIT_FUNCTIONS:
        values = [int(b) for b in response.bits[:count]]
    else:
        values = list(response.registers[:count])

    return ScanResult(
        address=address, count=count, function_code=function_code,
        values=values, ok=True, status="OK",
    )
