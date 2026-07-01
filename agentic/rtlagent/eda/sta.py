"""A small static timing analyzer over yosys JSON netlists.

After ``synth`` + ``abc -liberty rtlagent_generic.lib`` the netlist contains
only combinational cells from the bundled liberty plus yosys internal FF
cells (``$_DFF_*``, ``$_SDFF*``, ``$_DFFE_*`` ...).  This module computes
per-endpoint arrival times with a fixed per-cell delay model, yielding WNS,
TNS and reconstructed critical paths — the same signals a commercial STA
report gives the Dr.RTL-style agents, just from an open-source flow.

Delays are in nanoseconds and deliberately simple (no slew/load modeling):
the point is a *consistent, monotonic* cost surface for optimization, not
sign-off accuracy.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .metrics import PPAResult, TimingPath, TimingPathStep

log = logging.getLogger(__name__)

# Per-cell propagation delay (ns).  Must cover every cell in the liberty.
CELL_DELAYS: dict[str, float] = {
    "INV": 0.06,
    "BUF": 0.08,
    "NAND2": 0.10,
    "NOR2": 0.12,
    "AND2": 0.14,
    "OR2": 0.16,
    "NAND3": 0.14,
    "NOR3": 0.18,
    "XOR2": 0.20,
    "XNOR2": 0.20,
    "AOI21": 0.16,
    "OAI21": 0.16,
    "MUX2": 0.18,
}
DEFAULT_COMB_DELAY = 0.15

# Mirrors the liberty areas; FFs are not in the liberty (they stay as yosys
# internal cells), so their area lives here too.
CELL_AREAS: dict[str, float] = {
    "INV": 2, "BUF": 3, "NAND2": 4, "NOR2": 4, "AND2": 6, "OR2": 6,
    "NAND3": 6, "NOR3": 6, "XOR2": 8, "XNOR2": 8, "AOI21": 6, "OAI21": 6,
    "MUX2": 8,
}
FF_AREA = 16.0
FF_CLK_TO_Q = 0.12
FF_SETUP = 0.08
INPUT_DELAY = 0.0

_FF_PREFIXES = ("$_DFF", "$_SDFF", "$_DFFE", "$_SDFFE", "$_DFFSR", "$_ALDFF")
_LATCH_PREFIXES = ("$_DLATCH", "$_SR")


def is_ff(cell_type: str) -> bool:
    return cell_type.startswith(_FF_PREFIXES)


def is_latch(cell_type: str) -> bool:
    return cell_type.startswith(_LATCH_PREFIXES)


def _output_ports(cell: dict[str, Any]) -> list[str]:
    dirs = cell.get("port_directions", {})
    outs = [p for p, d in dirs.items() if d == "output"]
    if outs:
        return outs
    # ABC-mapped liberty cells carry no port_directions in write_json output;
    # every cell in the bundled liberty drives Y, FFs/latches drive Q.
    conns = cell.get("connections", {})
    return [p for p in ("Y", "Q") if p in conns]


def analyze(
    netlist: dict[str, Any],
    top: str,
    clock_period: float,
    max_paths: int = 10,
) -> PPAResult:
    """Run STA on a yosys ``write_json`` netlist dict for module ``top``."""
    mod = netlist.get("modules", {}).get(top)
    if mod is None:
        # Fall back to the only module (yosys may mangle the name).
        mods = netlist.get("modules", {})
        if len(mods) == 1:
            top, mod = next(iter(mods.items()))
        else:
            return PPAResult(ok=False, error=f"module '{top}' not found in netlist JSON")

    cells: dict[str, dict[str, Any]] = mod.get("cells", {})
    ports: dict[str, dict[str, Any]] = mod.get("ports", {})

    # --- net bookkeeping -------------------------------------------------
    # arrival[bit] = data arrival time; pred[bit] = (cell_name, from_bit)
    arrival: dict[int, float] = {}
    pred: dict[int, Optional[tuple[str, Optional[int]]]] = {}
    origin: dict[int, tuple[str, str]] = {}  # bit -> (startpoint name, kind)

    clock_bits: set[int] = set()
    for cname, cell in cells.items():
        if is_ff(cell["type"]):
            for b in cell.get("connections", {}).get("C", []):
                if isinstance(b, int):
                    clock_bits.add(b)

    # Primary inputs launch at INPUT_DELAY (clock nets excluded from data graph).
    for pname, port in ports.items():
        if port.get("direction") != "input":
            continue
        for b in port.get("bits", []):
            if isinstance(b, int) and b not in clock_bits:
                arrival[b] = INPUT_DELAY
                pred[b] = None
                origin[b] = (pname, "input")

    # FF/latch outputs launch at clk-to-Q.
    num_ffs = 0
    for cname, cell in cells.items():
        ctype = cell["type"]
        if is_ff(ctype) or is_latch(ctype):
            num_ffs += 1
            for port in _output_ports(cell) or ["Q"]:
                for b in cell.get("connections", {}).get(port, []):
                    if isinstance(b, int):
                        arrival[b] = FF_CLK_TO_Q
                        pred[b] = None
                        origin[b] = (cname, "ff")

    # --- combinational propagation (Kahn topological order) --------------
    comb_cells = {n: c for n, c in cells.items() if not is_ff(c["type"]) and not is_latch(c["type"])}
    # in-degree = number of input bits not yet resolved
    unresolved: dict[str, set[int]] = {}
    consumers: dict[int, list[str]] = {}
    unknown_types: set[str] = set()
    for cname, cell in comb_cells.items():
        outs = set(_output_ports(cell))
        need: set[int] = set()
        for port, bits in cell.get("connections", {}).items():
            if port in outs:
                continue
            for b in bits:
                if isinstance(b, int) and b not in arrival:
                    need.add(b)
                    consumers.setdefault(b, []).append(cname)
        unresolved[cname] = need
        if cell["type"] not in CELL_DELAYS and not cell["type"].startswith("$"):
            unknown_types.add(cell["type"])
    if unknown_types:
        log.warning("unknown cell types (default delay used): %s", sorted(unknown_types))

    ready = [n for n, need in unresolved.items() if not need]
    processed: set[str] = set()
    while ready:
        cname = ready.pop()
        if cname in processed:
            continue
        processed.add(cname)
        cell = comb_cells[cname]
        outs = set(_output_ports(cell))
        delay = CELL_DELAYS.get(cell["type"], DEFAULT_COMB_DELAY)
        worst_in, worst_bit = 0.0, None
        for port, bits in cell.get("connections", {}).items():
            if port in outs:
                continue
            for b in bits:
                if isinstance(b, int) and arrival.get(b, 0.0) >= worst_in:
                    worst_in, worst_bit = arrival.get(b, 0.0), b
        out_arrival = worst_in + delay
        for port in outs:
            for b in cell.get("connections", {}).get(port, []):
                if not isinstance(b, int):
                    continue
                if b not in arrival or out_arrival > arrival[b]:
                    arrival[b] = out_arrival
                    pred[b] = (cname, worst_bit)
                for consumer in consumers.get(b, []):
                    need = unresolved[consumer]
                    need.discard(b)
                    if not need and consumer not in processed:
                        ready.append(consumer)

    loop_cells = [n for n in comb_cells if n not in processed]
    if loop_cells:
        log.warning("%d cells unresolved (combinational loop or undriven nets)", len(loop_cells))

    # --- endpoints and slacks --------------------------------------------
    endpoints: list[tuple[str, str, float, Optional[int]]] = []  # (name, kind, arrival, bit)
    for cname, cell in cells.items():
        if not is_ff(cell["type"]) and not is_latch(cell["type"]):
            continue
        for b in cell.get("connections", {}).get("D", []):
            if isinstance(b, int):
                endpoints.append((cname, "ff", arrival.get(b, 0.0), b))
    for pname, port in ports.items():
        if port.get("direction") != "output":
            continue
        worst, wbit = 0.0, None
        for b in port.get("bits", []):
            if isinstance(b, int) and arrival.get(b, 0.0) >= worst:
                worst, wbit = arrival.get(b, 0.0), b
        endpoints.append((pname, "output", worst, wbit))

    paths: list[TimingPath] = []
    wns, tns = float("inf"), 0.0
    scored: list[tuple[float, str, str, float, Optional[int]]] = []
    for name, kind, arr, bit in endpoints:
        required = clock_period - (FF_SETUP if kind == "ff" else 0.0)
        slack = required - arr
        wns = min(wns, slack)
        if slack < 0:
            tns += slack
        scored.append((slack, name, kind, arr, bit))
    if wns == float("inf"):
        wns = clock_period  # purely combinational-free design
    scored.sort(key=lambda t: t[0])

    for slack, name, kind, arr, bit in scored[:max_paths]:
        required = clock_period - (FF_SETUP if kind == "ff" else 0.0)
        steps: list[TimingPathStep] = []
        b = bit
        # Walk back through predecessor cells.
        seen: set[int] = set()
        while b is not None and b not in seen:
            seen.add(b)
            p = pred.get(b)
            if p is None:
                break
            cname, from_bit = p
            ctype = cells[cname]["type"]
            steps.append(
                TimingPathStep(
                    cell=cname,
                    cell_type=ctype,
                    delay=CELL_DELAYS.get(ctype, DEFAULT_COMB_DELAY),
                    arrival=arrival.get(b, 0.0),
                )
            )
            b = from_bit
        steps.reverse()
        sp_name, sp_kind = origin.get(b, ("<const/undriven>", "input")) if b is not None else ("<const>", "input")
        paths.append(
            TimingPath(
                endpoint=name,
                endpoint_kind=kind,
                startpoint=sp_name,
                startpoint_kind=sp_kind,
                arrival=arr,
                required=required,
                slack=slack,
                steps=steps,
            )
        )

    # --- area --------------------------------------------------------------
    area = 0.0
    for cell in cells.values():
        t = cell["type"]
        if is_ff(t) or is_latch(t):
            area += FF_AREA
        else:
            area += CELL_AREAS.get(t, 5.0)

    return PPAResult(
        ok=True,
        top=top,
        clock_period=clock_period,
        wns=wns,
        tns=tns,
        area=area,
        num_cells=len(cells),
        num_ffs=num_ffs,
        critical_paths=paths,
    )
