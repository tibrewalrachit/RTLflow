"""Head-to-head evaluation: Dr.RTL baseline vs RTLflow-Agent.

Runs both harnesses on the same designs with the same LLM backend and
budget, and reports final PPA, composite score, and cost (synthesis runs,
SEC runs, LLM calls/tokens) side by side.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .harness import DesignSpec, DrRTLBaseline, HarnessConfig, RTLFlowAgent
from .harness.runner import RunResult
from .llm import create_backend

log = logging.getLogger(__name__)


@dataclass
class EvalRows:
    rows: list[dict] = field(default_factory=list)

    def render(self) -> str:
        if not self.rows:
            return "(no results)"
        hdr = (
            f"{'design':<16}{'harness':<16}{'WNS0':>8}{'WNS':>8}{'TNS0':>9}{'TNS':>9}"
            f"{'area0':>9}{'area':>9}{'score':>9}{'synth':>7}{'SEC':>5}{'LLM':>6}{'end':>19}"
        )
        lines = [hdr, "-" * len(hdr)]
        for r in self.rows:
            lines.append(
                f"{r['design']:<16}{r['harness']:<16}"
                f"{r['wns_baseline']:>8.3f}{r['wns_final']:>8.3f}"
                f"{r['tns_baseline']:>9.2f}{r['tns_final']:>9.2f}"
                f"{r['area_baseline']:>9.0f}{r['area_final']:>9.0f}"
                f"{r['score']:>+9.4f}{r['full_synth_runs']:>7}{r['sec_runs']:>5}"
                f"{r['llm_calls']:>6}{r['end_reason']:>19}"
            )
        return "\n".join(lines)

    def to_dict(self) -> list[dict]:
        return self.rows


def _row(res: RunResult) -> dict:
    return {
        "design": res.design,
        "harness": res.harness,
        "wns_baseline": res.baseline.wns,
        "wns_final": res.best.wns,
        "tns_baseline": res.baseline.tns,
        "tns_final": res.best.tns,
        "area_baseline": res.baseline.area,
        "area_final": res.best.area,
        "score": res.best_score,
        "rounds": res.rounds,
        "full_synth_runs": res.full_synth_runs,
        "sec_runs": res.sec_runs,
        "llm_calls": res.llm_calls,
        "llm_tokens": res.llm_tokens,
        "end_reason": res.end_reason,
    }


def run_eval(
    designs: list[DesignSpec],
    backend_spec: str,
    rounds: int = 4,
    work_root: str = "runs/eval",
    harnesses: tuple[str, ...] = ("baseline", "agentic"),
) -> EvalRows:
    rows = EvalRows()
    for spec in designs:
        for hname in harnesses:
            backend = create_backend(backend_spec)  # fresh usage counters per run
            cfg = HarnessConfig(max_major_rounds=rounds)
            cls = DrRTLBaseline if hname == "baseline" else RTLFlowAgent
            log.info("=== %s / %s ===", spec.name, hname)
            try:
                res = cls(spec, backend, work_root, cfg).run()
                rows.rows.append(_row(res))
                log.info(res.summary())
            except Exception as e:  # noqa: BLE001 — keep evaluating other designs
                log.error("%s/%s failed: %s", spec.name, hname, e)
                rows.rows.append(
                    {"design": spec.name, "harness": hname, "error": str(e),
                     "wns_baseline": 0.0, "wns_final": 0.0, "tns_baseline": 0.0,
                     "tns_final": 0.0, "area_baseline": 0.0, "area_final": 0.0,
                     "score": float("inf"), "rounds": 0, "full_synth_runs": 0,
                     "sec_runs": 0, "llm_calls": 0, "llm_tokens": 0,
                     "end_reason": "error"}
                )
    return rows
