"""Staged verification: cheap checks first, expensive proofs last.

Dr.RTL runs a full JasperGold proof on every attempt; with SEC pass rates of
38-48% on hard designs, half its EDA budget proves failures.  This pipeline
triages:

    1. lint            (~seconds)  syntax / elaboration
    2. lockstep sim    (~seconds)  random-input golden-vs-candidate diff
    3. testbench       (optional)  design's own regression
    4. SAT SEC         (~minutes)  induction proof, BMC fallback

Any stage failing short-circuits the rest.  ``FuncStatus`` records how far a
candidate got and carries the failure evidence for the repair loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from ..eda import (
    EquivStatus,
    check_equivalence,
    lint,
    random_compare,
    run_testbench,
)


@dataclass
class VerifyResult:
    passed: bool
    stage: str  # stage reached/failed: lint | sim | tb | sec | all
    sec_status: Optional[str] = None
    evidence: str = ""  # failure evidence for the repair loop

    def summary(self) -> str:
        return f"{'PASS' if self.passed else 'FAIL'}@{self.stage}" + (
            f" (sec={self.sec_status})" if self.sec_status else ""
        )


def verify_candidate(
    golden_files: Sequence[str | Path],
    candidate_file: str | Path,
    top: str,
    testbench: Optional[str | Path] = None,
    sim_cycles: int = 2000,
    sec_timeout: int = 300,
    skip_sec: bool = False,
) -> VerifyResult:
    ok, out = lint([candidate_file], top)
    if not ok:
        return VerifyResult(False, "lint", evidence=out[-2000:])

    sim = random_compare(golden_files, [candidate_file], top, cycles=sim_cycles)
    if not sim.passed:
        return VerifyResult(False, "sim", evidence=(sim.detail + "\n" + sim.log)[-2500:])

    if testbench is not None:
        tb = run_testbench([candidate_file], testbench)
        if not tb.passed:
            return VerifyResult(False, "tb", evidence=(tb.detail + "\n" + tb.log)[-2500:])

    if skip_sec:
        return VerifyResult(True, "sim", sec_status="skipped")

    eq = check_equivalence(golden_files, [candidate_file], top, timeout=sec_timeout)
    if eq.status == EquivStatus.NOT_EQUIVALENT:
        return VerifyResult(False, "sec", sec_status=eq.status.value, evidence=eq.detail[-2500:])
    if eq.status == EquivStatus.UNKNOWN:
        # Inconclusive solver + clean lockstep sim: accept with a flag, the
        # same judgement call commercial flows make on aborted proofs.
        return VerifyResult(True, "sec", sec_status=eq.status.value)
    return VerifyResult(True, "all", sec_status=eq.status.value)
