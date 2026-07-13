"""RTLflow-Agent: the improved agentic RTL optimization harness.

Targets every measured weakness of Dr.RTL's loop (see drrtl reproduction in
``baseline.py``) while keeping its verified-promotion discipline:

1. **Parallel candidate generation.** Each round fans out N optimizer calls
   with diverse directives and temperatures instead of 5 serial minors.
2. **Cheap triage before expensive EDA.** Candidates pass lint, then a
   MasterRTL-style SOG proxy ranks them; only the top-K get full synthesis
   and SEC.  (Dr.RTL runs full synthesis + a formal proof on everything,
   with SEC pass rates as low as ~40%.)
3. **Counterexample repair loop.** Verification failures feed the evidence
   (mismatch trace / SEC counterexample / lint error) back to the model for
   one repair attempt instead of discarding the transform.
4. **Beam over lineages.** The top ``beam_width`` verified versions stay
   alive as parents; a plateaued lineage can be abandoned (Dr.RTL is greedy
   single-lineage with no backtracking).
5. **Rich, grounded timing feedback.** The analyzer sees full per-cell
   critical paths from the built-in STA, not word-level slack pairs.
6. **Online learning.** Every full synthesis feeds the proxy (free training
   samples); skill statistics update in-loop; failed transforms are
   remembered per design and excluded from future prompts; new skills are
   extracted every few rounds, in-loop.
7. **Deterministic bookkeeping.** Scores, promotions and version files are
   handled by Python, never by the LLM.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..eda import composite_score
from ..eda.metrics import PPAResult
from ..proxy import PPAProxy, sog_features
from . import prompts
from .runner import Attempt, HarnessBase, RunResult

log = logging.getLogger(__name__)


@dataclass
class Lineage:
    version: str
    rtl: str
    ppa: PPAResult
    score: float
    stale_rounds: int = 0


class RTLFlowAgent(HarnessBase):
    name = "rtlflow-agent"

    def run(self) -> RunResult:
        cfg = self.cfg
        v0_rtl = self.design.rtl_text()
        self.work.write_version("v0", v0_rtl)
        baseline = self.synth(self.design.files)
        if not baseline.ok:
            raise RuntimeError(f"baseline synthesis failed: {baseline.error}")
        self.work.set_baseline(baseline)
        proxy = PPAProxy(self.work.root / "proxy.pkl")
        self._feed_proxy(proxy, self.design.files, baseline)
        log.info("[%s] v0: WNS=%.3f TNS=%.3f area=%.0f", self.design.name,
                 baseline.wns, baseline.tns, baseline.area)

        beam: list[Lineage] = [Lineage("v0", v0_rtl, baseline, 0.0)]
        version_counter = 0
        rounds_without_improvement = 0
        end_reason = "max_major_reached"

        for rnd in range(cfg.max_major_rounds):
            parent = min(beam, key=lambda l: (l.score, l.stale_rounds))
            log.info("[%s] round %d from %s (score %+.4f)",
                     self.design.name, rnd, parent.version, parent.score)

            # ANALYZE once per round with full per-cell path detail.
            analysis = self.analyze(parent.rtl, parent.ppa, degraded=False)

            # GENERATE candidates in parallel with diverse directives.
            directives = [
                prompts.DIRECTIVES[i % len(prompts.DIRECTIVES)]
                for i in range(cfg.candidates_per_round)
            ]
            temps = [cfg.temperature_spread[i % len(cfg.temperature_spread)]
                     for i in range(cfg.candidates_per_round)]
            with ThreadPoolExecutor(max_workers=cfg.parallel_workers) as pool:
                futures = [
                    pool.submit(self.optimize, parent.rtl, parent.ppa, analysis, d, t)
                    for d, t in zip(directives, temps)
                ]
                generated = [f.result() for f in futures]

            attempts: list[Attempt] = []
            for i, (rtl, transform) in enumerate(generated):
                tag = f"r{rnd}.c{i}"
                a = Attempt(tag=tag, transform=transform or "(no manifest)")
                if not rtl:
                    a.note = "no RTL in reply"
                elif rtl.strip() == parent.rtl.strip():
                    a.note = "no-op (identical RTL)"
                else:
                    a.rtl = rtl
                    a.file = self.work.write_attempt(tag, rtl)
                attempts.append(a)

            # TRIAGE 1: lint (cheap) — drop broken candidates immediately.
            from ..eda import lint

            viable: list[Attempt] = []
            for a in attempts:
                if a.file is None:
                    continue
                ok, out = lint([a.file], self.design.top)
                if ok:
                    viable.append(a)
                else:
                    a.note = "lint failed"
                    repaired = self._try_repair(parent.rtl, a, "lint", out[-1500:])
                    if repaired:
                        viable.append(a)

            # TRIAGE 2: proxy ranking — full EDA only for the top-K.
            ranked = self._proxy_rank(proxy, viable, parent)
            survivors = ranked[: cfg.proxy_keep]
            for a in ranked[cfg.proxy_keep:]:
                a.note = (a.note + "; dropped by proxy ranking").strip("; ")

            # EVALUATE + VERIFY survivors (parallel; yosys is subprocess-bound).
            with ThreadPoolExecutor(max_workers=cfg.parallel_workers) as pool:
                list(pool.map(lambda a: self._evaluate(a, baseline, proxy, parent), survivors))

            # Bookkeeping + skill stats.
            for a in attempts:
                self.work.record_attempt(a.tag, a.record())
                if a.file is not None and a.verify is not None:
                    success = a.promotable and a.score.total < parent.score
                    self.skills.record_outcome(_skill_of(a.transform, self.skills), success)
                    if not a.verify.passed:
                        self.skills.record_failed_transform(self.design.name, a.transform)

            # PROMOTE: best verified candidate that improves on its parent.
            winners = [a for a in survivors if a.promotable and a.score.total < parent.score]
            round_rec = {
                "round": rnd,
                "parent": parent.version,
                "candidates": [
                    {"tag": a.tag, "transform": a.transform,
                     "verify": a.verify.summary() if a.verify else None,
                     "score": a.score.total if a.score else None, "note": a.note}
                    for a in attempts
                ],
            }
            if winners:
                winner = min(winners, key=lambda a: a.score.total)
                version_counter += 1
                new_version = f"v{version_counter}"
                self.work.write_version(new_version, winner.rtl)
                beam.append(Lineage(new_version, winner.rtl, winner.ppa, winner.score.total))
                beam.sort(key=lambda l: l.score)
                beam[:] = beam[: cfg.beam_width]
                parent.stale_rounds = 0
                rounds_without_improvement = 0
                round_rec["promoted"] = {"tag": winner.tag, "version": new_version,
                                         "score": winner.score.total}
                log.info("[%s] promoted %s -> %s (score %+.4f)",
                         self.design.name, winner.tag, new_version, winner.score.total)
            else:
                parent.stale_rounds += 1
                rounds_without_improvement += 1
                round_rec["promoted"] = None
            self.work.add_round(round_rec)

            # In-loop skill extraction.
            if (rnd + 1) % cfg.extract_skills_every == 0:
                try:
                    self.extract_skills(attempts)
                except Exception as e:  # noqa: BLE001 — extraction is best-effort
                    log.warning("skill extraction failed: %s", e)

            if rounds_without_improvement > cfg.no_improvement_patience:
                end_reason = "no_improvement"
                break

        best = min(beam, key=lambda l: l.score)
        self.work.finish(end_reason, best.version, best.ppa, vars(self.backend.usage))
        return self._result(baseline, best.ppa, best.version, best.score,
                            rounds=len(self.work.history["major_rounds"]),
                            end_reason=end_reason)

    # -- internals ------------------------------------------------------------

    def _feed_proxy(self, proxy: PPAProxy, files, ppa: PPAResult) -> None:
        feats = sog_features(files, self.design.top, self.design.clock_period)
        if feats is not None and ppa.ok:
            proxy.add_sample(feats, ppa.wns, ppa.tns, ppa.area)
            proxy.calibrate_delay(feats.values["est_delay"], ppa.max_delay)

    def _proxy_rank(self, proxy: PPAProxy, attempts: list[Attempt], parent: Lineage) -> list[Attempt]:
        if len(attempts) <= self.cfg.proxy_keep:
            return attempts
        parent_pred = proxy.predict(self.design.files, self.design.top, self.design.clock_period)
        scored: list[tuple[float, Attempt]] = []
        for a in attempts:
            pred = proxy.predict([a.file], self.design.top, self.design.clock_period)
            if pred is None or parent_pred is None:
                scored.append((1e9, a))  # unrankable -> lowest priority
                a.note = (a.note + "; proxy failed").strip("; ")
            else:
                s = pred.score(parent_pred)
                a.note = (a.note + f"; proxy_score={s:.4f} ({pred.source})").strip("; ")
                scored.append((s, a))
        scored.sort(key=lambda t: t[0])
        return [a for _, a in scored]

    def _evaluate(self, a: Attempt, baseline: PPAResult, proxy: PPAProxy, parent: Lineage) -> None:
        a.ppa = self.synth([a.file])
        if a.ppa.ok:
            self._feed_proxy(proxy, [a.file], a.ppa)
        a.verify = self.verify(a.file)
        if not a.verify.passed and self.cfg.repair_attempts > 0:
            if self._try_repair(parent.rtl, a, a.verify.stage, a.verify.evidence):
                a.ppa = self.synth([a.file])
                if a.ppa.ok:
                    self._feed_proxy(proxy, [a.file], a.ppa)
                a.verify = self.verify(a.file)
        if a.ppa.ok and a.verify.passed:
            a.score = composite_score(a.ppa, baseline)
        log.info("[%s] %s: %s score=%s", self.design.name, a.tag,
                 a.verify.summary() if a.verify else "n/a",
                 f"{a.score.total:+.4f}" if a.score else "null")

    def _try_repair(self, golden_rtl: str, a: Attempt, stage: str, evidence: str) -> bool:
        """One repair round-trip; returns True if a plausible fix was produced."""
        if a.rtl is None:
            return False
        from .verify import VerifyResult

        vr = a.verify or VerifyResult(False, stage, evidence=evidence)
        try:
            fixed, transform = self.repair(golden_rtl, a.rtl, a.transform, vr)
        except Exception as e:  # noqa: BLE001
            log.warning("repair call failed: %s", e)
            return False
        if not fixed or fixed.strip() == a.rtl.strip():
            return False
        a.rtl = fixed
        a.file = self.work.write_attempt(a.tag + ".fix", fixed)
        a.transform = (transform or a.transform) + " [repaired]"
        a.note = (a.note + f"; repaired after {stage} failure").strip("; ")
        return True


def _skill_of(transform: str, skills) -> Optional[str]:
    t = (transform or "").lower()
    for name in skills.skills:
        if name.lower() in t:
            return name
    return None
