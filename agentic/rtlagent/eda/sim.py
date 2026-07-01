"""Simulation checks with Icarus Verilog.

Two verification modes:

* ``run_testbench`` — run a design-provided self-checking testbench; the
  bench must print ``TEST PASSED`` or ``TEST FAILED``.
* ``random_compare`` — auto-generated lockstep testbench instantiating the
  golden and revised designs side by side, driving identical constrained
  random inputs and comparing every output each cycle.  This is the
  simulation half of the promotion gate (SAT-based SEC is the other half).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .yosys import run_yosys


@dataclass
class SimResult:
    passed: bool
    detail: str = ""
    log: str = ""


def _iverilog() -> Optional[str]:
    return shutil.which("iverilog")


def run_testbench(
    design_files: Sequence[str | Path],
    tb_file: str | Path,
    timeout: int = 300,
    defines: Optional[dict[str, str]] = None,
) -> SimResult:
    ivl = _iverilog()
    if not ivl:
        return SimResult(False, "iverilog not installed")
    with tempfile.TemporaryDirectory(prefix="rtlagent_sim_") as td:
        out = Path(td) / "sim.vvp"
        cmd = [ivl, "-g2012", "-o", str(out)]
        for k, v in (defines or {}).items():
            cmd.append(f"-D{k}={v}")
        cmd += [str(Path(f).resolve()) for f in [*design_files, tb_file]]
        comp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if comp.returncode != 0:
            return SimResult(False, "compile failed", comp.stdout + comp.stderr)
        try:
            run = subprocess.run(
                ["vvp", str(out)], capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return SimResult(False, f"simulation timed out after {timeout}s")
        log = run.stdout + run.stderr
        if "TEST PASSED" in log and "TEST FAILED" not in log:
            return SimResult(True, "testbench passed", log[-2000:])
        return SimResult(False, "testbench reported failure or no PASS marker", log[-4000:])


# ---------------------------------------------------------------------------
# Auto-generated golden-vs-revised lockstep comparison
# ---------------------------------------------------------------------------

_CLOCK_RE = re.compile(r"(^|_)(clk|clock)(_|$)|^clk", re.IGNORECASE)
_RESET_RE = re.compile(r"(^|_)(rst|reset)", re.IGNORECASE)
_ACTIVE_LOW_RE = re.compile(r"(_n|_b|_l|n)$", re.IGNORECASE)


def get_ports(files: Sequence[str | Path], top: str) -> Optional[dict[str, dict]]:
    """Return {name: {"direction": .., "width": ..}} for the top module."""
    with tempfile.TemporaryDirectory(prefix="rtlagent_ports_") as td:
        jf = Path(td) / "ports.json"
        reads = "\n".join(f"read_verilog -sv {Path(f).resolve()}" for f in files)
        ok, _ = run_yosys(f"{reads}\nhierarchy -check -top {top}\nproc\nwrite_json {jf}\n")
        if not ok or not jf.exists():
            return None
        data = json.loads(jf.read_text())
    mod = data.get("modules", {}).get(top)
    if mod is None:
        return None
    return {
        name: {"direction": p["direction"], "width": len(p.get("bits", []))}
        for name, p in mod.get("ports", {}).items()
    }


def _rename_copy(files: Sequence[str | Path], top: str, new_top: str, out_file: Path) -> bool:
    reads = "\n".join(f"read_verilog -sv {Path(f).resolve()}" for f in files)
    ok, _ = run_yosys(
        f"""{reads}
prep -top {top} -flatten
memory_map
rename {top} {new_top}
write_verilog -noattr {out_file}
"""
    )
    return ok and out_file.exists()


def random_compare(
    golden_files: Sequence[str | Path],
    revised_files: Sequence[str | Path],
    top: str,
    cycles: int = 2000,
    seed: int = 1,
    timeout: int = 300,
) -> SimResult:
    """Lockstep random simulation of golden vs revised implementations."""
    ports = get_ports(golden_files, top)
    if not ports:
        return SimResult(False, "could not extract ports from golden design")
    rports = get_ports(revised_files, top)
    if rports != ports:
        return SimResult(False, f"port mismatch between golden and revised: {ports} vs {rports}")

    ins = {n: p for n, p in ports.items() if p["direction"] == "input"}
    outs = {n: p for n, p in ports.items() if p["direction"] == "output"}
    clocks = [n for n in ins if _CLOCK_RE.search(n)]
    resets = [n for n in ins if n not in clocks and _RESET_RE.search(n)]
    data_ins = {n: p for n, p in ins.items() if n not in clocks and n not in resets}

    with tempfile.TemporaryDirectory(prefix="rtlagent_cmp_") as td:
        tdp = Path(td)
        gold_v, rev_v = tdp / "gold.v", tdp / "rev.v"
        if not _rename_copy(golden_files, top, "rtlagent_gold", gold_v):
            return SimResult(False, "yosys failed to prepare golden copy")
        if not _rename_copy(revised_files, top, "rtlagent_rev", rev_v):
            return SimResult(False, "yosys failed to prepare revised copy")

        tb = _gen_tb(clocks, resets, data_ins, outs, cycles, seed)
        tb_file = tdp / "tb_cmp.v"
        tb_file.write_text(tb)
        return run_testbench([gold_v, rev_v], tb_file, timeout=timeout)


def _gen_tb(
    clocks: list[str],
    resets: list[str],
    data_ins: dict[str, dict],
    outs: dict[str, dict],
    cycles: int,
    seed: int,
) -> str:
    decl, conn_g, conn_r, drive = [], [], [], []
    for n in clocks:
        decl.append(f"  reg {n};")
    for n in resets:
        decl.append(f"  reg {n};")
    for n, p in data_ins.items():
        w = p["width"]
        decl.append(f"  reg [{w-1}:0] {n};" if w > 1 else f"  reg {n};")
        nwords = (w + 31) // 32
        expr = "{" + ", ".join("$random(rseed)" for _ in range(nwords)) + "}"
        drive.append(f"      {n} <= {expr};")
    for n, p in outs.items():
        w = p["width"]
        decl.append(f"  wire [{w-1}:0] {n}_g, {n}_r;" if w > 1 else f"  wire {n}_g, {n}_r;")
    for group, suffix in ((conn_g, "_g"), (conn_r, "_r")):
        for n in clocks + resets + list(data_ins):
            group.append(f".{n}({n})")
        for n in outs:
            group.append(f".{n}({n}{suffix})")

    compares = "\n".join(
        f"      if ({n}_g !== {n}_r) begin\n"
        f'        $display("MISMATCH %0t port {n}: gold=%h rev=%h", $time, {n}_g, {n}_r);\n'
        f"        errors = errors + 1;\n      end"
        for n in outs
    )
    reset_asserts = "\n".join(
        f"    {n} = {0 if _ACTIVE_LOW_RE.search(n) else 1};" for n in resets
    )
    reset_deasserts = "\n".join(
        f"    {n} = {1 if _ACTIVE_LOW_RE.search(n) else 0};" for n in resets
    )
    clk = clocks[0] if clocks else None
    clk_gen = (
        "\n".join(f"  initial {n} = 0;" for n in clocks)
        + "\n"
        + "\n".join(f"  always #5 {n} = ~{n};" for n in clocks)
        if clocks
        else "  reg __virt_clk;\n  initial __virt_clk = 0;\n  always #5 __virt_clk = ~__virt_clk;"
    )
    tick = clk or "__virt_clk"

    return f"""// Auto-generated lockstep comparison testbench (rtlagent)
`timescale 1ns/1ps
module tb_cmp;
  integer errors;
  integer i;
  integer rseed;
{chr(10).join(decl)}

{clk_gen}

  rtlagent_gold u_gold ({', '.join(conn_g)});
  rtlagent_rev  u_rev  ({', '.join(conn_r)});

  initial begin
    rseed = {seed};
    errors = 0;
    // Initialize data inputs before reset release: X on any input (e.g. an
    // enable) would poison both instances identically and mask real diffs.
{chr(10).join(d.replace('<=', '=').lstrip() and '    ' + d.replace('<=', '=').strip() for d in drive) if drive else ''}
{reset_asserts if resets else ''}
    repeat (5) @(posedge {tick});
{reset_deasserts if resets else ''}
    for (i = 0; i < {cycles}; i = i + 1) begin
      @(posedge {tick});
{chr(10).join(drive) if drive else ''}
      @(negedge {tick});
{compares}
    end
    if (errors == 0) $display("TEST PASSED");
    else $display("TEST FAILED: %0d mismatches", errors);
    $finish;
  end
endmodule
"""
