"""Yosys synthesis driver: RTL -> mapped netlist -> PPA via the STA engine."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from . import sta
from .metrics import PPAResult

log = logging.getLogger(__name__)

LIBERTY = Path(__file__).parent / "liberty" / "rtlagent_generic.lib"


class YosysNotFound(RuntimeError):
    pass


def _yosys_bin() -> str:
    path = shutil.which("yosys")
    if not path:
        raise YosysNotFound(
            "yosys not found on PATH. Install it (e.g. `apt-get install yosys`)."
        )
    return path


def run_yosys(script: str, timeout: int = 600, quiet: bool = True) -> tuple[bool, str]:
    """Run a yosys script, return (ok, combined_output)."""
    with tempfile.NamedTemporaryFile("w", suffix=".ys", delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        proc = subprocess.run(
            [_yosys_bin(), *(["-q"] if quiet else []), "-s", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = proc.stdout + proc.stderr
        return proc.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"yosys timed out after {timeout}s"
    finally:
        Path(script_path).unlink(missing_ok=True)


def lint(verilog_files: Sequence[str | Path], top: Optional[str] = None) -> tuple[bool, str]:
    """Fast syntax/elaboration check without full synthesis."""
    reads = "\n".join(f"read_verilog -sv {Path(f)}" for f in verilog_files)
    top_arg = f"-top {top}" if top else "-auto-top"
    script = f"{reads}\nhierarchy -check {top_arg}\nproc\nopt_clean\n"
    return run_yosys(script, timeout=120)


def synthesize(
    verilog_files: Sequence[str | Path],
    top: str,
    clock_period: float,
    work_dir: Optional[str | Path] = None,
    timeout: int = 600,
    max_paths: int = 10,
) -> PPAResult:
    """Synthesize with yosys+ABC against the bundled liberty and run STA.

    Combinational logic is mapped to liberty cells; flip-flops stay as yosys
    internal ``$_DFF*`` cells (the STA engine prices them directly), which
    sidesteps liberty FF-mapping fragility across reset/enable flavors.
    """
    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="rtlagent_syn_"))
    work.mkdir(parents=True, exist_ok=True)
    json_out = work / "netlist.json"
    reads = "\n".join(f"read_verilog -sv {Path(f).resolve()}" for f in verilog_files)
    # -noalumacc keeps arithmetic as RTL-shaped adder structures instead of
    # fusing chains into $macc cells whose techmap expansion is already
    # tree-balanced.  This mirrors a plain DC `compile` (Dr.RTL's flow):
    # local logic optimization happens (ABC), but the RTL's arithmetic
    # structure survives — which is the whole point of RTL-level timing
    # optimization.
    script = f"""{reads}
hierarchy -check -top {top}
synth -top {top} -flatten -noalumacc
abc -liberty {LIBERTY}
opt_clean -purge
write_json {json_out}
"""
    ok, out = run_yosys(script, timeout=timeout)
    (work / "yosys.log").write_text(out)
    if not ok or not json_out.exists():
        return PPAResult(ok=False, top=top, clock_period=clock_period, error=_extract_error(out), log=out)
    try:
        netlist = json.loads(json_out.read_text())
    except json.JSONDecodeError as e:
        return PPAResult(ok=False, top=top, clock_period=clock_period, error=f"bad netlist JSON: {e}", log=out)
    result = sta.analyze(netlist, top=top, clock_period=clock_period, max_paths=max_paths)
    result.log = out[-4000:]
    return result


def _extract_error(out: str) -> str:
    lines = [l for l in out.splitlines() if "ERROR" in l or "error" in l.lower()]
    return "\n".join(lines[-10:]) if lines else out[-1500:]
