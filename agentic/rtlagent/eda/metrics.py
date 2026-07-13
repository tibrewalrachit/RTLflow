"""PPA metrics and the composite optimization score.

The composite score follows Dr.RTL's formulation:

    score = 0.5 * WNS_norm + 0.35 * TNS_norm + 0.15 * Area_norm + penalty

where each component is normalized against the baseline (version 0) design so
that the baseline scores 1.0 on every axis; lower is better.  A penalty is
added for designs that fail verification (they should normally be discarded
before scoring, but the penalty keeps the ordering sane if they are not).
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TimingPathStep:
    cell: str  # instance name
    cell_type: str  # liberty cell / FF type
    delay: float  # incremental delay contributed by this step (ns)
    arrival: float  # arrival time after this step (ns)


@dataclass
class TimingPath:
    endpoint: str  # FF D-pin instance or primary output name
    endpoint_kind: str  # "ff" | "output"
    startpoint: str  # FF Q-pin instance or primary input name
    startpoint_kind: str  # "ff" | "input"
    arrival: float  # data arrival time at endpoint (ns)
    required: float  # required time (clock period - setup) (ns)
    slack: float  # required - arrival (ns)
    steps: list[TimingPathStep] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Startpoint: {self.startpoint} ({self.startpoint_kind})",
            f"Endpoint:   {self.endpoint} ({self.endpoint_kind})",
            f"{'cell':<44}{'type':<10}{'incr':>8}{'arrival':>9}",
        ]
        for s in self.steps:
            lines.append(f"{s.cell[:43]:<44}{s.cell_type:<10}{s.delay:>8.3f}{s.arrival:>9.3f}")
        lines.append(f"data arrival time  {self.arrival:9.3f}")
        lines.append(f"data required time {self.required:9.3f}")
        verdict = "MET" if self.slack >= 0 else "VIOLATED"
        lines.append(f"slack ({verdict})     {self.slack:9.3f}")
        return "\n".join(lines)


@dataclass
class PPAResult:
    """Result of one synthesis + STA run."""

    ok: bool
    top: str = ""
    clock_period: float = 0.0  # ns (constraint)
    wns: float = 0.0  # ns; negative = violation
    tns: float = 0.0  # ns; <= 0, sum of negative slacks
    area: float = 0.0  # library area units (gates + FFs)
    num_cells: int = 0
    num_ffs: int = 0
    critical_paths: list[TimingPath] = field(default_factory=list)
    log: str = ""
    error: str = ""

    @property
    def max_delay(self) -> float:
        """Longest data arrival (ns) — achievable clock period ignoring setup."""
        if not self.critical_paths:
            return 0.0
        return max(p.arrival for p in self.critical_paths)

    def timing_report(self, max_paths: int = 5) -> str:
        """Human/LLM readable report in the spirit of DC's report_timing."""
        if not self.ok:
            return f"SYNTHESIS FAILED\n{self.error}"
        head = [
            f"top module      : {self.top}",
            f"clock period    : {self.clock_period:.3f} ns",
            f"WNS             : {self.wns:.3f} ns",
            f"TNS             : {self.tns:.3f} ns",
            f"area            : {self.area:.1f}",
            f"cells / FFs     : {self.num_cells} / {self.num_ffs}",
            "",
            f"---- {min(max_paths, len(self.critical_paths))} worst timing paths ----",
        ]
        body = [p.render() for p in self.critical_paths[:max_paths]]
        return "\n".join(head) + "\n" + "\n\n".join(body)

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), indent=2)


@dataclass
class Score:
    total: float
    wns_norm: float
    tns_norm: float
    area_norm: float
    penalty: float

    def render(self) -> str:
        return (
            f"score={self.total:.4f} (wns_norm={self.wns_norm:.4f}, "
            f"tns_norm={self.tns_norm:.4f}, area_norm={self.area_norm:.4f}, "
            f"penalty={self.penalty:.2f})"
        )


# Dr.RTL composite-score weights and penalty rule.
W_WNS = 0.5
W_TNS = 0.35
W_AREA = 0.15
AREA_PENALTY = 0.5  # applied when area grows more than 10% over baseline
AREA_PENALTY_THRESHOLD = 0.10
FAIL_PENALTY = 10.0
_CLAMP = 5.0


def _rel(value: float, baseline: float) -> float:
    """Dr.RTL normalization: signed relative change (X - X_base) / |X_base|.

    Baseline maps to 0.0; improvements on WNS/TNS (which are negative under
    an infeasible constraint) come out negative.  Terms are clamped so a
    near-zero baseline cannot blow up the score.
    """
    denom = max(abs(baseline), 1e-6)
    return max(-_CLAMP, min(_CLAMP, (value - baseline) / denom))


def composite_score(candidate: PPAResult, baseline: PPAResult, verified: bool = True) -> Score:
    """Dr.RTL composite score; lower is better, baseline (v0) scores 0.0.

    score = 0.5*WNS_norm + 0.35*TNS_norm + 0.15*Area_norm + penalty, with
    X_norm = (X - X_base)/|X_base| and penalty = 0.5 if area grew >10%.
    Unverified / failed candidates get a large penalty (Dr.RTL simply never
    promotes them; the penalty keeps any accidental comparison sane).
    """
    # WNS/TNS enter as violation magnitudes so that reducing a violation
    # yields a negative (better) term — matching Dr.RTL's recorded examples
    # (wns_norm=-0.289 for an improvement).  If the baseline already meets
    # timing, track critical delay instead so the optimizer keeps a gradient.
    base_viol_wns = max(0.0, -baseline.wns)
    if base_viol_wns > 1e-6:
        wns_norm = _rel(max(0.0, -candidate.wns), base_viol_wns)
    else:
        wns_norm = _rel(candidate.max_delay, baseline.max_delay)
    tns_norm = _rel(max(0.0, -candidate.tns), max(0.0, -baseline.tns))
    area_norm = _rel(candidate.area, baseline.area)
    penalty = AREA_PENALTY if area_norm > AREA_PENALTY_THRESHOLD else 0.0
    if not candidate.ok:
        penalty += FAIL_PENALTY
    if not verified:
        penalty += FAIL_PENALTY
    total = W_WNS * wns_norm + W_TNS * tns_norm + W_AREA * area_norm + penalty
    if math.isnan(total):
        total = float("inf")
    return Score(total=total, wns_norm=wns_norm, tns_norm=tns_norm, area_norm=area_norm, penalty=penalty)
