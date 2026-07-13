"""Skill memory: reusable RTL optimization patterns with success tracking.

Dr.RTL ships a manually curated skill pack (~47 <pattern, strategy, example>
entries tiered by empirical SEC-pass/success rate) and extracts new skills
offline.  This store keeps the same shape but updates statistics online
during a run, remembers failed transforms per design (so the optimizer stops
re-proposing them), and supports in-loop extraction of new skills.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Skill:
    name: str
    pattern: str  # what RTL structure this applies to
    strategy: str  # the transformation to perform
    example: str = ""  # optional before/after sketch
    attempts: int = 0
    successes: int = 0  # verified AND improved score

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.5  # optimistic prior

    def render(self) -> str:
        rate = f"{100 * self.success_rate:.0f}%" if self.attempts else "untried"
        text = f"### {self.name} (success rate: {rate})\nApplies to: {self.pattern}\nStrategy: {self.strategy}"
        if self.example:
            text += f"\nExample:\n{self.example}"
        return text


# Starter skills: the classic timing transforms Dr.RTL's pack encodes (its
# highest-success tiers), rewritten as generic patterns.
STARTER_SKILLS = [
    Skill(
        name="balance-operator-tree",
        pattern="A serial chain of associative operations (a+b+c+d... or and/or/xor reductions) on the critical path",
        strategy="Restructure the chain into a balanced binary tree using explicit parentheses or intermediate wires, cutting logic depth from O(n) to O(log n). Keep bit widths and rounding identical.",
        example="s = ((a+b)+(c+d)) + ((e+f)+(g+h));  // instead of a+b+c+d+e+f+g+h left-to-right",
    ),
    Skill(
        name="condition-precompute",
        pattern="A complex condition (wide comparison, reduction, chained logic) evaluated inside the critical combinational cone",
        strategy="Hoist the condition into its own wire computed in parallel with (not in series after) the datapath, or restructure so the late-arriving signal steers the final mux only.",
    ),
    Skill(
        name="one-hot-predecode",
        pattern="Binary-encoded select decoded deep in the datapath (case/nested ternaries on an encoded field)",
        strategy="Pre-decode the selector into one-hot enables in parallel with operand computation, then use AND-OR selection instead of a mux cascade.",
    ),
    Skill(
        name="mux-tree-flatten",
        pattern="Nested ternary/if-else chains creating a serial priority mux cascade where the cases are actually mutually exclusive",
        strategy="Replace the priority chain with a parallel case / one-hot AND-OR structure so all cases evaluate concurrently. Only when cases are provably mutually exclusive.",
    ),
    Skill(
        name="late-select-early-compute",
        pattern="Result computed after a mux whose select arrives late",
        strategy="Duplicate the downstream computation on both mux inputs and move the mux to the end, so the late select steers between precomputed results (speculation).",
    ),
    Skill(
        name="common-subexpression-share",
        pattern="The same subexpression computed in multiple places feeding the critical path via different routes",
        strategy="Factor the subexpression into one wire; if it is on the critical path, compute it once as early as possible.",
    ),
    Skill(
        name="carry-save-accumulate",
        pattern="Multiple additions whose full carry-propagate results are only needed at the end (accumulation, multiply-add chains)",
        strategy="Keep intermediate sums in redundant carry-save form (3:2 compressors expressed as separate sum/carry vectors) and do a single carry-propagate add at the end. Preserve exact bit widths.",
    ),
    Skill(
        name="split-wide-comparison",
        pattern="A wide equality/magnitude comparison on the critical path",
        strategy="Split the comparison into parallel slices combined with a shallow AND/OR tree; for equality, XOR + reduction-NOR of slices.",
    ),
]

# Anti-patterns Dr.RTL learned the hard way (0% tiers / SEC killers).
ANTI_PATTERNS = [
    "Do NOT add, remove, or move pipeline registers — latency must not change.",
    "Do NOT change module ports, names, widths, or reset behavior.",
    "Do NOT change counter directions or FSM state encodings.",
    "Do NOT rewrite memory/array inference styles (RAM inference must stay identical).",
    "Do NOT 'optimize' LFSRs or arithmetic that relies on specific overflow/truncation behavior — bit-exact semantics are required.",
    "Do NOT pre-register or retime input selectors — that changes cycle semantics.",
]


class SkillMemory:
    def __init__(self, path: Optional[str | Path] = None, seed_defaults: bool = True):
        self.path = Path(path) if path else None
        self.skills: dict[str, Skill] = {}
        self.failed_transforms: dict[str, list[str]] = {}  # design -> descriptions
        if self.path and self.path.exists():
            self._load()
        elif seed_defaults:
            for s in STARTER_SKILLS:
                self.skills[s.name] = s

    # -- selection ----------------------------------------------------------

    def top_skills(self, k: int = 6) -> list[Skill]:
        return sorted(self.skills.values(), key=lambda s: -s.success_rate)[:k]

    def render_for_prompt(self, k: int = 6) -> str:
        parts = [s.render() for s in self.top_skills(k)]
        return "\n\n".join(parts)

    def render_anti_patterns(self, design: str = "") -> str:
        lines = list(ANTI_PATTERNS)
        for desc in self.failed_transforms.get(design, [])[-8:]:
            lines.append(f"Do NOT retry this previously-failed transform: {desc}")
        return "\n".join(f"- {l}" for l in lines)

    # -- online updates -------------------------------------------------------

    def record_outcome(self, skill_name: Optional[str], success: bool) -> None:
        if skill_name and skill_name in self.skills:
            s = self.skills[skill_name]
            s.attempts += 1
            if success:
                s.successes += 1
            self._save()

    def record_failed_transform(self, design: str, description: str) -> None:
        self.failed_transforms.setdefault(design, []).append(description[:300])
        self._save()

    def add_skill(self, skill: Skill) -> None:
        if skill.name not in self.skills:
            self.skills[skill.name] = skill
            self._save()

    # -- persistence ------------------------------------------------------------

    def _save(self) -> None:
        if not self.path:
            return
        payload = {
            "skills": {n: asdict(s) for n, s in self.skills.items()},
            "failed_transforms": self.failed_transforms,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))

    def _load(self) -> None:
        payload = json.loads(self.path.read_text())
        self.skills = {n: Skill(**d) for n, d in payload.get("skills", {}).items()}
        self.failed_transforms = payload.get("failed_transforms", {})
