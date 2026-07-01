"""Shared machinery for the baseline (Dr.RTL) and improved (RTLflow-Agent)
optimization harnesses."""

from __future__ import annotations

import dataclasses
import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..eda import PPAResult, composite_score, synthesize
from ..eda.metrics import Score
from ..llm import LLMBackend, extract_json, extract_verilog
from . import prompts
from .design import DesignSpec
from .skills import SkillMemory
from .verify import VerifyResult, verify_candidate
from .workdir import WorkDir

log = logging.getLogger(__name__)


@dataclass
class HarnessConfig:
    max_major_rounds: int = 10
    minors_per_round: int = 5
    # improved-harness knobs
    candidates_per_round: int = 6
    proxy_keep: int = 3  # candidates surviving proxy ranking to full synth
    beam_width: int = 2
    repair_attempts: int = 1
    no_improvement_patience: int = 1  # rounds without promotion before stopping
    sim_cycles: int = 1500
    sec_timeout: int = 240
    synth_timeout: int = 420
    max_paths_in_report: int = 8
    parallel_workers: int = 4
    extract_skills_every: int = 3
    temperature_spread: tuple[float, ...] = (0.2, 0.5, 0.8)


@dataclass
class Attempt:
    tag: str
    transform: str = ""
    rtl: Optional[str] = None
    file: Optional[Path] = None
    ppa: Optional[PPAResult] = None
    verify: Optional[VerifyResult] = None
    score: Optional[Score] = None
    skill_used: Optional[str] = None
    note: str = ""

    @property
    def promotable(self) -> bool:
        return (
            self.ppa is not None
            and self.ppa.ok
            and self.verify is not None
            and self.verify.passed
            and self.score is not None
        )

    def record(self) -> dict:
        return {
            "tag": self.tag,
            "transform": self.transform,
            "ppa": dataclasses.asdict(self.ppa) if self.ppa else None,
            "verify": dataclasses.asdict(self.verify) if self.verify else None,
            "score": dataclasses.asdict(self.score) if self.score else None,
            "note": self.note,
        }


@dataclass
class RunResult:
    design: str
    harness: str
    baseline: PPAResult
    best: PPAResult
    best_version: str
    best_score: float
    rounds: int
    full_synth_runs: int
    sec_runs: int
    llm_calls: int
    llm_tokens: int
    end_reason: str
    workdir: Path

    def summary(self) -> str:
        b, f = self.baseline, self.best
        return (
            f"[{self.harness}] {self.design}: WNS {b.wns:.3f} -> {f.wns:.3f} ns, "
            f"TNS {b.tns:.3f} -> {f.tns:.3f} ns, area {b.area:.0f} -> {f.area:.0f}, "
            f"score {self.best_score:+.4f} ({self.rounds} rounds, "
            f"{self.full_synth_runs} synth, {self.sec_runs} SEC, {self.llm_calls} LLM calls, "
            f"end: {self.end_reason})"
        )


class HarnessBase:
    name = "base"

    def __init__(
        self,
        design: DesignSpec,
        backend: LLMBackend,
        work_root: str | Path,
        config: Optional[HarnessConfig] = None,
        skills: Optional[SkillMemory] = None,
    ):
        self.design = design
        self.backend = backend
        self.cfg = config or HarnessConfig()
        self.work = WorkDir(work_root, f"{design.name}.{self.name}")
        self.skills = skills or SkillMemory(self.work.root / "skills.json")
        self.full_synth_runs = 0
        self.sec_runs = 0

    # -- EDA steps ------------------------------------------------------------

    def synth(self, files: list[Path]) -> PPAResult:
        self.full_synth_runs += 1
        with tempfile.TemporaryDirectory(prefix="rtlagent_ppa_") as td:
            return synthesize(
                files,
                top=self.design.top,
                clock_period=self.design.clock_period,
                work_dir=td,
                timeout=self.cfg.synth_timeout,
                max_paths=self.cfg.max_paths_in_report,
            )

    def verify(self, candidate_file: Path, sim_cycles: Optional[int] = None) -> VerifyResult:
        self.sec_runs += 1
        return verify_candidate(
            self.design.files,
            candidate_file,
            self.design.top,
            testbench=self.design.testbench,
            sim_cycles=sim_cycles or self.cfg.sim_cycles,
            sec_timeout=self.cfg.sec_timeout,
        )

    # -- LLM steps ---------------------------------------------------------------

    def analyze(self, rtl: str, ppa: PPAResult, history_note: str = "", degraded: bool = False) -> str:
        report = self._word_level_report(ppa) if degraded else ppa.timing_report(self.cfg.max_paths_in_report)
        resp = self.backend.chat(
            prompts.ANALYZER_USER.format(
                name=self.design.name,
                top=self.design.top,
                clock_period=self.design.clock_period,
                rtl=rtl,
                timing_report=report,
                history_note=history_note or "This is the first analysis of this version.",
            ),
            system=prompts.ANALYZER_SYSTEM,
        )
        data = extract_json(resp.text)
        return json.dumps(data, indent=2) if data else resp.text[:3000]

    def optimize(
        self, rtl: str, ppa: PPAResult, analysis: str, directive: str, temperature: Optional[float] = None
    ) -> tuple[Optional[str], str]:
        """Returns (candidate_rtl, transform_manifest)."""
        resp = self.backend.chat(
            prompts.OPTIMIZER_USER.format(
                name=self.design.name,
                top=self.design.top,
                clock_period=self.design.clock_period,
                wns=ppa.wns,
                tns=ppa.tns,
                area=ppa.area,
                rtl=rtl,
                analysis=analysis,
                skills=self.skills.render_for_prompt(),
                anti_patterns=self.skills.render_anti_patterns(self.design.name),
                directive=directive,
            ),
            system=prompts.OPTIMIZER_SYSTEM,
            temperature=temperature,
        )
        return extract_verilog(resp.text), _manifest(resp.text)

    def repair(self, golden: str, candidate: str, transform: str, vr: VerifyResult) -> tuple[Optional[str], str]:
        resp = self.backend.chat(
            prompts.REPAIR_USER.format(
                golden=golden,
                candidate=candidate,
                transform=transform or "unspecified",
                stage=vr.stage,
                evidence=vr.evidence[-2000:] or "no detail",
            ),
            system=prompts.REPAIR_SYSTEM,
        )
        return extract_verilog(resp.text), _manifest(resp.text)

    def extract_skills(self, attempts: list[Attempt]) -> None:
        interesting = [a for a in attempts if a.transform]
        if not interesting:
            return
        log_lines = [
            f"- {a.tag}: {a.transform} -> {a.verify.summary() if a.verify else 'n/a'}, "
            f"score={a.score.total:+.4f}" if a.score else f"- {a.tag}: {a.transform} -> failed"
            for a in interesting
        ]
        resp = self.backend.chat(
            prompts.EXTRACTOR_USER.format(
                name=self.design.name,
                attempts_log="\n".join(log_lines),
                known_skills=", ".join(self.skills.skills),
            ),
            system=prompts.EXTRACTOR_SYSTEM,
        )
        data = extract_json(resp.text)
        if isinstance(data, dict):
            from .skills import Skill

            for s in data.get("skills", [])[:2]:
                if isinstance(s, dict) and s.get("name") and s.get("strategy"):
                    self.skills.add_skill(
                        Skill(
                            name=str(s["name"])[:60],
                            pattern=str(s.get("pattern", ""))[:400],
                            strategy=str(s["strategy"])[:600],
                            example=str(s.get("example", ""))[:600],
                        )
                    )

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _word_level_report(ppa: PPAResult) -> str:
        """Dr.RTL-style degraded feedback: endpoint -> slack pairs only."""
        lines = [
            f"WNS {ppa.wns:.3f} ns, TNS {ppa.tns:.3f} ns, area {ppa.area:.0f}",
            "worst endpoint slacks:",
        ]
        for p in ppa.critical_paths:
            lines.append(f"  {p.startpoint} -> {p.endpoint} : {p.slack:.3f}")
        return "\n".join(lines)

    def _result(self, baseline: PPAResult, best: PPAResult, best_version: str,
                best_score: float, rounds: int, end_reason: str) -> RunResult:
        return RunResult(
            design=self.design.name,
            harness=self.name,
            baseline=baseline,
            best=best,
            best_version=best_version,
            best_score=best_score,
            rounds=rounds,
            full_synth_runs=self.full_synth_runs,
            sec_runs=self.sec_runs,
            llm_calls=self.backend.usage.calls,
            llm_tokens=self.backend.usage.input_tokens + self.backend.usage.output_tokens,
            end_reason=end_reason,
            workdir=self.work.root,
        )


def _manifest(text: str) -> str:
    for line in text.splitlines():
        if line.strip().upper().startswith("TRANSFORM:"):
            return line.strip()[len("TRANSFORM:"):].strip()
    return ""
