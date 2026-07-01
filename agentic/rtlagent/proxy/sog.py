"""Simple Operator Graph (SOG) extraction — MasterRTL reproduction.

MasterRTL (ICCAD'23) bit-blasts RTL with yosys (proc/flatten/opt/fsm/memory/
techmap) into single-bit simple operators (And/Or/Not/Xor/Mux + DFF), then
computes per-design feature vectors and analytical timing over the operator
graph.  We follow the same recipe but read yosys' JSON netlist directly
instead of re-parsing emitted Verilog through Pyverilog (the approach its
successor RTL-Timer adopted).

Constants below are MasterRTL's published ``std_PPA.json`` values
(NanGate45-derived; area in um^2, delay in ns).
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from ..eda.yosys import run_yosys

# --- std_PPA.json constants (MasterRTL) -----------------------------------
AREA_SEQ_DFF = 4.522
AREA_COMB = {"and": 1.064, "or": 1.064, "not": 0.798, "xor": 1.596, "mux": 1.862}
STAT_PWR = {"dff": 0.07911, "and": 0.02507, "or": 0.02269, "not": 0.106, "xor": 0.03616, "mux": 0.03593}
DYN_PWR = {"dff": 3.1, "and": 3.1, "or": 3.1, "not": 1.8, "xor": 2.45, "mux": 2.6}
# Analytical delay weights: node delay = fanout * weight.
DELAY_W = {"and": 0.42, "mux": 0.42, "or": 0.27, "not": 0.27, "xor": 0.74}
DELAY_W_REG = 1.0
DEFAULT_TOGGLE = 0.08

# yosys internal simple gates -> SOG operator classes
_GATE_CLASS = {
    "$_AND_": "and", "$_NAND_": "and", "$_ANDNOT_": "and",
    "$_OR_": "or", "$_NOR_": "or", "$_ORNOT_": "or",
    "$_NOT_": "not", "$_BUF_": "not",
    "$_XOR_": "xor", "$_XNOR_": "xor",
    "$_MUX_": "mux", "$_NMUX_": "mux",
    "$_AOI3_": "and", "$_OAI3_": "or", "$_AOI4_": "and", "$_OAI4_": "or",
}

FEATURE_NAMES = [
    "seq_num", "fanout_sum", "io_num",
    "and_num", "or_num", "not_num", "xor_num", "mux_num",
    "seq_area", "comb_area", "total_area",
    "stat_pwr", "dyn_pwr", "total_pwr",
    "logic_depth", "est_delay", "est_wns", "est_tns", "n_endpoints_violated",
]


@dataclass
class SOGFeatures:
    values: dict[str, float] = field(default_factory=dict)

    def vector(self) -> list[float]:
        return [self.values.get(n, 0.0) for n in FEATURE_NAMES]

    def render(self) -> str:
        return "\n".join(f"{n:>22} : {self.values.get(n, 0.0):.4f}" for n in FEATURE_NAMES)


def sog_netlist(files: Sequence[str | Path], top: str, timeout: int = 300) -> Optional[dict[str, Any]]:
    """Bit-blast to yosys internal simple gates and return the JSON netlist.

    This is MasterRTL's SOG yosys recipe (no ABC, no liberty) — much cheaper
    than full synthesis, which is what makes the proxy useful as an
    inner-loop ranker.
    """
    with tempfile.TemporaryDirectory(prefix="rtlagent_sog_") as td:
        out = Path(td) / "sog.json"
        reads = "\n".join(f"read_verilog -sv {Path(f).resolve()}" for f in files)
        script = f"""{reads}
hierarchy -check -top {top}
proc
flatten
opt
fsm
opt
memory
opt
techmap
opt
write_json {out}
"""
        ok, _ = run_yosys(script, timeout=timeout)
        if not ok or not out.exists():
            return None
        data = json.loads(out.read_text())
    mods = data.get("modules", {})
    if top in mods:
        return mods[top]
    return next(iter(mods.values()), None)


def _is_ff(t: str) -> bool:
    return t.startswith(("$_DFF", "$_SDFF", "$_DFFE", "$_SDFFE", "$_DFFSR", "$_ALDFF", "$_DLATCH", "$_SR"))


def extract_features(
    mod: dict[str, Any],
    clock_period: float,
) -> SOGFeatures:
    """MasterRTL's 14-d area/power vector + analytical-timing features."""
    cells = mod.get("cells", {})
    ports = mod.get("ports", {})

    counts = {"and": 0, "or": 0, "not": 0, "xor": 0, "mux": 0}
    n_ff = 0
    driver: dict[int, str] = {}
    fanout: dict[str, int] = {}

    clock_bits: set[int] = set()
    for cell in cells.values():
        if _is_ff(cell["type"]):
            for b in cell.get("connections", {}).get("C", []):
                if isinstance(b, int):
                    clock_bits.add(b)

    for cname, cell in cells.items():
        t = cell["type"]
        if _is_ff(t):
            n_ff += 1
        elif t in _GATE_CLASS:
            counts[_GATE_CLASS[t]] += 1
        out_port = "Q" if _is_ff(t) else "Y"
        for b in cell.get("connections", {}).get(out_port, []):
            if isinstance(b, int):
                driver[b] = cname

    # Fanout: how many cell inputs each cell's output feeds.
    for cell in cells.values():
        out_port = "Q" if _is_ff(cell["type"]) else "Y"
        for port, bits in cell.get("connections", {}).items():
            if port == out_port:
                continue
            for b in bits:
                if isinstance(b, int) and b in driver:
                    fanout[driver[b]] = fanout.get(driver[b], 0) + 1

    io_num = sum(len(p.get("bits", [])) for p in ports.values())
    ff_fanout_sum = sum(fanout.get(n, 0) for n, c in cells.items() if _is_ff(c["type"]))

    seq_area = AREA_SEQ_DFF * n_ff
    comb_area = sum(AREA_COMB[k] * v for k, v in counts.items())
    stat_pwr = STAT_PWR["dff"] * n_ff + sum(STAT_PWR[k] * v for k, v in counts.items())
    dyn_pwr = (DYN_PWR["dff"] * n_ff + sum(DYN_PWR[k] * v for k, v in counts.items())) * DEFAULT_TOGGLE

    # --- analytical timing: longest path with fanout-weighted node delays --
    arrival: dict[int, float] = {}
    depth: dict[int, int] = {}
    for pname, port in ports.items():
        if port.get("direction") == "input":
            for b in port.get("bits", []):
                if isinstance(b, int) and b not in clock_bits:
                    arrival[b] = 0.0
                    depth[b] = 0
    reg_launch = DELAY_W_REG  # Reg weight (fanout factor folded into scale)
    comb = {}
    for cname, cell in cells.items():
        if _is_ff(cell["type"]):
            fo = max(1, fanout.get(cname, 1))
            for b in cell.get("connections", {}).get("Q", []):
                if isinstance(b, int):
                    arrival[b] = reg_launch * min(fo, 8) * 0.1
                    depth[b] = 0
        elif cell["type"] in _GATE_CLASS:
            comb[cname] = cell

    unresolved: dict[str, set[int]] = {}
    consumers: dict[int, list[str]] = {}
    for cname, cell in comb.items():
        need = set()
        for port, bits in cell.get("connections", {}).items():
            if port == "Y":
                continue
            for b in bits:
                if isinstance(b, int) and b not in arrival:
                    need.add(b)
                    consumers.setdefault(b, []).append(cname)
        unresolved[cname] = need

    ready = [n for n, need in unresolved.items() if not need]
    processed: set[str] = set()
    while ready:
        cname = ready.pop()
        if cname in processed:
            continue
        processed.add(cname)
        cell = comb[cname]
        klass = _GATE_CLASS[cell["type"]]
        fo = max(1, fanout.get(cname, 1))
        d = DELAY_W[klass] * min(fo, 8) * 0.1
        worst, wd = 0.0, 0
        for port, bits in cell.get("connections", {}).items():
            if port == "Y":
                continue
            for b in bits:
                if isinstance(b, int):
                    worst = max(worst, arrival.get(b, 0.0))
                    wd = max(wd, depth.get(b, 0))
        out_a, out_d = worst + d, wd + 1
        for b in cell.get("connections", {}).get("Y", []):
            if not isinstance(b, int):
                continue
            if out_a > arrival.get(b, -1.0):
                arrival[b] = out_a
                depth[b] = out_d
            for cons in consumers.get(b, []):
                need = unresolved[cons]
                need.discard(b)
                if not need and cons not in processed:
                    ready.append(cons)

    # Endpoints: FF D pins and primary outputs.
    slacks: list[float] = []
    est_delay = 0.0
    logic_depth = 0
    for cname, cell in cells.items():
        if _is_ff(cell["type"]):
            for b in cell.get("connections", {}).get("D", []):
                if isinstance(b, int):
                    a = arrival.get(b, 0.0)
                    est_delay = max(est_delay, a)
                    logic_depth = max(logic_depth, depth.get(b, 0))
                    slacks.append(clock_period - a)
    for pname, port in ports.items():
        if port.get("direction") == "output":
            for b in port.get("bits", []):
                if isinstance(b, int):
                    a = arrival.get(b, 0.0)
                    est_delay = max(est_delay, a)
                    logic_depth = max(logic_depth, depth.get(b, 0))
                    slacks.append(clock_period - a)

    est_wns = min(slacks) if slacks else clock_period
    est_tns = sum(s for s in slacks if s < 0)
    n_viol = sum(1 for s in slacks if s < 0)

    return SOGFeatures(
        values={
            "seq_num": float(n_ff),
            "fanout_sum": float(ff_fanout_sum),
            "io_num": float(io_num),
            "and_num": float(counts["and"]),
            "or_num": float(counts["or"]),
            "not_num": float(counts["not"]),
            "xor_num": float(counts["xor"]),
            "mux_num": float(counts["mux"]),
            "seq_area": seq_area,
            "comb_area": comb_area,
            "total_area": seq_area + comb_area,
            "stat_pwr": stat_pwr,
            "dyn_pwr": dyn_pwr,
            "total_pwr": stat_pwr + dyn_pwr,
            "logic_depth": float(logic_depth),
            "est_delay": est_delay,
            "est_wns": est_wns,
            "est_tns": est_tns,
            "n_endpoints_violated": float(n_viol),
        }
    )


def sog_features(
    files: Sequence[str | Path], top: str, clock_period: float
) -> Optional[SOGFeatures]:
    mod = sog_netlist(files, top)
    if mod is None:
        return None
    return extract_features(mod, clock_period)
