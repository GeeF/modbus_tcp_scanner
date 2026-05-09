"""Textual TUI for scanning Modbus TCP registers."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
)

import scanner


FC_OPTIONS: list[tuple[str, int]] = [
    ("0x01 Read Coils", 0x01),
    ("0x02 Read Discrete Inputs", 0x02),
    ("0x03 Read Holding Registers", 0x03),
    ("0x04 Read Input Registers", 0x04),
]


def parse_address(s: str) -> int:
    """Accept 0x-prefixed hex or plain decimal. Raises ValueError on garbage."""
    s = s.strip()
    if not s:
        raise ValueError("address is empty")
    if s.lower().startswith("0x"):
        return int(s, 16)
    return int(s, 10)


def format_values(function_code: int, values: list[int]) -> str:
    if function_code in scanner.BIT_FUNCTIONS:
        return " ".join(str(v) for v in values)
    return " ".join(f"0x{v:04X} ({v})" for v in values)


class ModbusScanApp(App):
    """A Modbus TCP register scanner."""

    CSS = """
    #connection, #params {
        height: auto;
        padding: 0 1;
    }
    #connection > Horizontal, #params > Horizontal {
        height: 4;
    }
    .section-title {
        color: $text-muted;
        text-style: bold;
        height: 1;
    }
    .field {
        width: 1fr;
        height: 4;
        margin: 0 1 0 0;
    }
    .field > Label {
        height: 1;
        color: $text-muted;
    }
    #buttons {
        height: 3;
        align: center middle;
        padding: 0 1;
    }
    #buttons > Button {
        margin: 0 1;
    }
    #results {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "start", "Start"),
        ("x", "stop", "Stop"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._scan_task: asyncio.Task | None = None
        self._row_counter = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        with Vertical(id="connection"):
            yield Label("Connection", classes="section-title")
            with Horizontal():
                with Vertical(classes="field"):
                    yield Label("Host / IP")
                    yield Input(value="127.0.0.1", id="host")
                with Vertical(classes="field"):
                    yield Label("Port")
                    yield Input(value="502", id="port")
                with Vertical(classes="field"):
                    yield Label("Unit / Slave ID")
                    yield Input(value="1", id="unit")

        with Vertical(id="params"):
            yield Label("Scan parameters", classes="section-title")
            with Horizontal():
                with Vertical(classes="field"):
                    yield Label("Function code")
                    yield Select(FC_OPTIONS, value=0x03, allow_blank=False, id="fc")
                with Vertical(classes="field"):
                    yield Label("Start address (dec or 0x..)")
                    yield Input(value="0", id="start")
                with Vertical(classes="field"):
                    yield Label("End address (dec or 0x..)")
                    yield Input(value="31", id="end")
                with Vertical(classes="field"):
                    yield Label("Registers per read")
                    yield Input(value="8", id="count")

        with Horizontal(id="buttons"):
            yield Button("Start scan", id="start-btn", variant="primary")
            yield Button("Stop", id="stop-btn", variant="error", disabled=True)
            yield Button("Clear results", id="clear-btn")

        yield DataTable(id="results", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.add_columns(
            "#", "Address (hex)", "Address (dec)", "Count", "FC", "Values", "Status"
        )
        table.cursor_type = "row"

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            await self._start_scan()
        elif event.button.id == "stop-btn":
            self._stop_scan()
        elif event.button.id == "clear-btn":
            self._clear_results()

    async def action_start(self) -> None:
        await self._start_scan()

    def action_stop(self) -> None:
        self._stop_scan()

    def _clear_results(self) -> None:
        table = self.query_one("#results", DataTable)
        table.clear()
        self._row_counter = 0

    async def _start_scan(self) -> None:
        if self._scan_task is not None and not self._scan_task.done():
            return
        try:
            params = self._read_params()
        except ValueError as exc:
            self.notify(str(exc), severity="error", title="Invalid input")
            return

        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#stop-btn", Button).disabled = False
        self._scan_task = asyncio.create_task(self._run_scan(**params))

    def _stop_scan(self) -> None:
        if self._scan_task is not None and not self._scan_task.done():
            self._scan_task.cancel()

    def _read_params(self) -> dict:
        host = self.query_one("#host", Input).value.strip()
        if not host:
            raise ValueError("Host is required")
        try:
            port = int(self.query_one("#port", Input).value)
        except ValueError:
            raise ValueError("Port must be an integer") from None
        if not (1 <= port <= 65535):
            raise ValueError("Port must be in 1..65535")
        try:
            unit = int(self.query_one("#unit", Input).value)
        except ValueError:
            raise ValueError("Unit ID must be an integer") from None
        if not (0 <= unit <= 247):
            raise ValueError("Unit ID must be in 0..247")
        fc = int(self.query_one("#fc", Select).value)
        try:
            start = parse_address(self.query_one("#start", Input).value)
            end = parse_address(self.query_one("#end", Input).value)
        except ValueError:
            raise ValueError("Addresses must be decimal or 0x-prefixed hex") from None
        if start < 0 or end < 0 or start > 0xFFFF or end > 0xFFFF:
            raise ValueError("Addresses must be in 0..0xFFFF")
        if end < start:
            raise ValueError("End address must be >= start address")
        try:
            count = int(self.query_one("#count", Input).value)
        except ValueError:
            raise ValueError("Registers per read must be an integer") from None
        max_count = scanner.max_count_for(fc)
        if not (1 <= count <= max_count):
            raise ValueError(f"Registers per read must be in 1..{max_count} for FC 0x{fc:02X}")
        return dict(
            host=host, port=port, unit=unit,
            fc=fc, start=start, end=end, count=count,
        )

    async def _run_scan(
        self, host: str, port: int, unit: int,
        fc: int, start: int, end: int, count: int,
    ) -> None:
        table = self.query_one("#results", DataTable)
        try:
            async for result in scanner.scan(host, port, unit, fc, start, end, count):
                self._row_counter += 1
                values_text = (
                    format_values(result.function_code, result.values)
                    if result.values is not None else ""
                )
                status = (
                    Text(result.status, style="red")
                    if not result.ok else Text(result.status, style="green")
                )
                table.add_row(
                    str(self._row_counter),
                    f"0x{result.address:04X}",
                    str(result.address),
                    str(result.count),
                    f"0x{result.function_code:02X}",
                    values_text,
                    status,
                )
        except asyncio.CancelledError:
            self.notify("Scan stopped", severity="warning")
        except Exception as exc:
            self.notify(f"Scan failed: {exc}", severity="error")
        finally:
            self.query_one("#start-btn", Button).disabled = False
            self.query_one("#stop-btn", Button).disabled = True
            self._scan_task = None
