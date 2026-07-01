"""Dr.RTL reproduction: the baseline serial optimization loop.

Faithful to the published workflow, ported to open-source EDA:

* up to 10 major rounds (v0 -> v9), 5 minor attempts each;
* every minor is ANALYZE -> OPTIMIZE -> EVALUATE (full synthesis) ->
  VERIFY (full SEC vs v0) -> RECORD, strictly serial;
* no pre-filtering, no repair loop, no parallelism, no beam — the round's
  best verified minor with an improved score is promoted, else the run stops
  with ``no_improvement``;
* the analyzer sees Dr.RTL's information regime: word-level
  ``startpoint -> endpoint : slack`` pairs only (not per-cell paths);
* score: 0.5*WNS_norm + 0.35*TNS_norm + 0.15*Area_norm (+0.5 area penalty),
  normalized against v0.

Deliberate deviations (documented, both harness-neutral): scoring/promotion
arithmetic is deterministic Python instead of in-context LLM bookkeeping,
and Synopsys DC + JasperGold are replaced by yosys+ABC and SAT-based SEC.
"""

from __future__ import annotations

import logging

from ..eda import composite_score
from . import prompts
from .runner import Attempt, HarnessBase, RunResult

log = logging.getLogger(__name__)


class DrRTLBaseline(HarnessBase):
    name = "drrtl-baseline"

    def run(self) -> RunResult:
        v0_rtl = self.design.rtl_text()
        self.work.write_version("v0", v0_rtl)
        baseline = self.synth(self.design.files)
        if not baseline.ok:
            raise RuntimeError(f"baseline synthesis failed: {baseline.error}")
        self.work.set_baseline(baseline)
        log.info("[%s] v0: WNS=%.3f TNS=%.3f area=%.0f", self.design.name,
                 baseline.wns, baseline.tns, baseline.area)

        current_rtl, current_ppa = v0_rtl, baseline
        best_version, best_score = "v0", 0.0
        end_reason = "max_major_reached"

        for major in range(self.cfg.max_major_rounds):
            attempts: list[Attempt] = []
            tried_notes: list[str] = []
            for minor in range(1, self.cfg.minors_per_round + 1):
                tag = f"v{major}.{minor}"
                attempt = Attempt(tag=tag)
                history_note = (
                    "Transforms already attempted on this version:\n" + "\n".join(tried_notes)
                    if tried_notes
                    else ""
                )
                # ANALYZE (degraded, word-level feedback — like Dr.RTL)
                analysis = self.analyze(current_rtl, current_ppa, history_note, degraded=True)
                # OPTIMIZE
                rtl, transform = self.optimize(
                    current_rtl, current_ppa, analysis, directive=prompts.DIRECTIVES[0]
                )
                attempt.transform = transform or "(no manifest)"
                tried_notes.append(f"- {tag}: {attempt.transform}")
                if not rtl:
                    attempt.note = "no RTL in optimizer reply"
                    attempts.append(attempt)
                    self.work.record_attempt(tag, attempt.record())
                    continue
                attempt.rtl = rtl
                attempt.file = self.work.write_attempt(tag, rtl)
                # EVALUATE: full synthesis, always (no pre-filter)
                attempt.ppa = self.synth([attempt.file])
                # VERIFY: full SEC vs v0, always
                attempt.verify = self.verify(attempt.file)
                if attempt.ppa.ok and attempt.verify.passed:
                    attempt.score = composite_score(attempt.ppa, baseline)
                log.info("[%s] %s: %s score=%s", self.design.name, tag,
                         attempt.verify.summary() if attempt.verify else "n/a",
                         f"{attempt.score.total:+.4f}" if attempt.score else "null")
                attempts.append(attempt)
                self.work.record_attempt(tag, attempt.record())

            # RECORD / promote: best verified minor, only if it beats the
            # current best score (a round without improvement ends the run).
            promotable = [a for a in attempts if a.promotable and a.score.total < best_score]
            round_rec = {
                "major_version": f"v{major}",
                "minors": [
                    {"version": a.tag, "sec": a.verify.summary() if a.verify else "n/a",
                     "score": a.score.total if a.score else None}
                    for a in attempts
                ],
            }
            if not promotable:
                round_rec["promoted"] = None
                self.work.add_round(round_rec)
                end_reason = "no_improvement"
                break
            winner = min(promotable, key=lambda a: a.score.total)
            new_version = f"v{major + 1}"
            self.work.write_version(new_version, winner.rtl)
            current_rtl, current_ppa = winner.rtl, winner.ppa
            best_version, best_score = new_version, winner.score.total
            round_rec["promoted"] = winner.tag
            self.work.add_round(round_rec)
            log.info("[%s] promoted %s -> %s (score %+.4f)",
                     self.design.name, winner.tag, new_version, best_score)

        self.work.finish(end_reason, best_version, current_ppa,
                         vars(self.backend.usage))
        return self._result(baseline, current_ppa, best_version, best_score,
                            rounds=len(self.work.history["major_rounds"]),
                            end_reason=end_reason)
