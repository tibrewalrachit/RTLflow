"""Sequential equivalence checking with yosys SAT.

Open-source stand-in for the Formality/JasperGold step in Dr.RTL's flow:

1. temporal-induction proof (``sat -tempinduct``) — full sequential proof
   when it converges;
2. bounded model check fallback (``sat -seq N``) — catches real bugs and
   yields a qualified "bounded pass" when induction is inconclusive;
3. callers should additionally run simulation regression (see ``sim.py``)
   — the harness treats SEC and simulation as independent gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence

from .yosys import run_yosys


class EquivStatus(str, Enum):
    EQUIVALENT = "equivalent"  # proven by temporal induction
    BOUNDED_PASS = "bounded_pass"  # no mismatch within BMC depth
    NOT_EQUIVALENT = "not_equivalent"  # counterexample found
    UNKNOWN = "unknown"  # solver timeout / setup failure


@dataclass
class EquivResult:
    status: EquivStatus
    detail: str = ""

    @property
    def acceptable(self) -> bool:
        """SEC gate used for version promotion (bounded pass counts, but the
        harness pairs it with simulation)."""
        return self.status in (EquivStatus.EQUIVALENT, EquivStatus.BOUNDED_PASS)


def _prep_script(files: Sequence[str | Path], top: str, stash: str) -> str:
    reads = "\n".join(f"read_verilog -sv {Path(f).resolve()}" for f in files)
    return f"""{reads}
prep -top {top} -flatten
memory_map
opt -full
async2sync
design -stash {stash}
"""


def check_equivalence(
    golden_files: Sequence[str | Path],
    revised_files: Sequence[str | Path],
    top: str,
    bmc_depth: int = 30,
    timeout: int = 300,
) -> EquivResult:
    common = (
        _prep_script(golden_files, top, "gold")
        + _prep_script(revised_files, top, "rev")
        + f"""design -copy-from gold -as gold {top}
design -copy-from rev -as rev {top}
miter -equiv -flatten -make_assert gold rev miter
hierarchy -top miter
"""
    )

    # Pass 1: temporal induction (full sequential proof).  Without -verify
    # yosys prints unambiguous outcome markers instead of aborting.
    ok, out = run_yosys(
        common + "sat -prove-asserts -tempinduct -maxsteps 12 -set-init-undef miter\n",
        timeout=timeout,
        quiet=False,
    )
    if "model found for base case: FAIL" in out:
        # A base-case model is a genuine counterexample.
        return EquivResult(EquivStatus.NOT_EQUIVALENT, _tail(out))
    if ok and "SUCCESS!" in out:
        return EquivResult(EquivStatus.EQUIVALENT, "temporal induction proof succeeded")

    # Pass 2 (induction inconclusive): bounded model check from a defined
    # all-zero initial state.
    ok, out = run_yosys(
        common + f"sat -prove-asserts -seq {bmc_depth} -set-init-zero miter\n",
        timeout=timeout,
        quiet=False,
    )
    if "model found: FAIL" in out:
        return EquivResult(EquivStatus.NOT_EQUIVALENT, _tail(out))
    if ok and "SUCCESS!" in out:
        return EquivResult(EquivStatus.BOUNDED_PASS, f"no mismatch within {bmc_depth} cycles")
    return EquivResult(EquivStatus.UNKNOWN, _tail(out))


def _tail(out: str, n: int = 2500) -> str:
    return out[-n:]
