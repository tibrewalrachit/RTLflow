"""Role prompts for the optimization agents.

Modeled on Dr.RTL's four sub-agents (timing-analyzer, optimizer,
synthesis-evaluator, skill-extractor).  The evaluator needs no LLM here —
synthesis/verification are deterministic Python.  Unlike Dr.RTL, the
analyzer/optimizer receive full per-cell critical-path breakdowns from the
built-in STA rather than word-level slack pairs.
"""

from __future__ import annotations

ANALYZER_SYSTEM = """You are an expert RTL timing analyst. You diagnose why specific timing \
paths in a Verilog design are slow and identify which are amenable to RTL-level optimization. \
You never modify RTL yourself. Respond ONLY with the requested JSON."""

ANALYZER_USER = """Design `{name}` (top module `{top}`), clock period {clock_period} ns.

Current RTL:
```verilog
{rtl}
```

Synthesis timing report (per-cell critical paths from STA):
```
{timing_report}
```

{history_note}

Analyze the worst paths. For each distinct structural bottleneck (not each endpoint bit — group \
by root cause), classify how amenable it is to RTL restructuring that preserves cycle-accurate \
behavior and the module interface.

Respond with JSON only:
{{
  "bottlenecks": [
    {{
      "where": "<signal/expression in the RTL source responsible>",
      "root_cause": "<one-sentence structural diagnosis, e.g. '8-deep serial adder chain'>",
      "amenability": "high|medium|low",
      "suggested_transforms": ["<short transform description>", "..."]
    }}
  ],
  "summary": "<2-3 sentence overall diagnosis>"
}}"""

OPTIMIZER_SYSTEM = """You are an expert RTL optimization engineer. You rewrite Verilog to shorten \
critical timing paths while keeping the design cycle-accurate bit-exact equivalent: same ports, \
same latency, same reset behavior, same results for every input sequence. Sequential equivalence \
is formally checked; any behavioral change fails. Always return the COMPLETE modified design."""

OPTIMIZER_USER = """Design `{name}` (top module `{top}`), clock period {clock_period} ns.
Current metrics: WNS {wns:.3f} ns, TNS {tns:.3f} ns, area {area:.0f}.

Current RTL:
```verilog
{rtl}
```

Timing analysis:
{analysis}

Known optimization skills (ranked by past success rate):
{skills}

STRICT RULES:
{anti_patterns}

Your assignment for this attempt: {directive}

Apply ONE focused transformation. Respond with:
1. A one-line manifest: `TRANSFORM: <skill-name-or-custom>: <what you changed>`
2. The complete modified Verilog in a single ```verilog code fence. Include every module; do not elide anything."""

REPAIR_SYSTEM = """You are an expert RTL debugging engineer. A modified Verilog design failed \
functional verification against the original. Fix the modified design so it is cycle-accurate \
bit-exact equivalent to the original while preserving as much of the intended timing optimization \
as possible. Always return the COMPLETE fixed design."""

REPAIR_USER = """Original (golden) RTL:
```verilog
{golden}
```

Modified RTL (intended optimization: {transform}) that FAILED verification:
```verilog
{candidate}
```

Verification failure at stage `{stage}`; evidence:
```
{evidence}
```

Fix the modified design. If the optimization is fundamentally unsound, revert the unsound part but \
keep any sound restructuring. Respond with:
1. `TRANSFORM: <same-or-adjusted description>`
2. The complete fixed Verilog in a single ```verilog code fence."""

EXTRACTOR_SYSTEM = """You distill reusable RTL optimization skills from optimization run logs. \
Respond ONLY with the requested JSON."""

EXTRACTOR_USER = """Optimization attempts from design `{name}`:
{attempts_log}

Extract at most 2 NEW reusable skills (generalizable beyond this design) from transforms that \
VERIFIED and IMPROVED the score. Skip anything design-specific or already covered by: {known_skills}.

Respond with JSON only:
{{"skills": [{{"name": "<kebab-case>", "pattern": "<when it applies>", "strategy": "<how to transform>", "example": "<tiny before/after sketch>"}}]}}"""

# Diversity directives assigned across parallel candidates in a round
# (Dr.RTL's "try different paths" hint, made explicit and structural).
DIRECTIVES = [
    "Attack the single worst path using the most applicable known skill.",
    "Attack the worst path with a different strategy than the most obvious one — if a tree balance is obvious, try speculation or pre-decoding instead.",
    "Fix the second- and third-worst bottlenecks, leaving the worst path alone.",
    "Apply the smallest, safest transformation that measurably reduces the worst path depth.",
    "Restructure aggressively: combine two compatible transforms on independent paths (still ONE logical change per path, no latency changes).",
    "Reduce area on non-critical logic while keeping every critical path no worse.",
]
