# rtlagent — Agentic RTL Timing Optimization on Open-Source EDA

`rtlagent` reproduces the methodology of two HKUST-zhiyao frameworks on a
fully open-source stack, then goes beyond them with an improved agentic
harness that plugs in **Anthropic (Claude)** or **open-weight models (GLM
5.x, DeepSeek, Qwen, anything OpenAI-compatible)**:

* **[Dr.RTL](https://github.com/hkust-zhiyao/Dr_RTL)** — *Autonomous Agentic
  RTL optimization through Tool-Grounded Self-Improvement*: an LLM agent loop
  that iteratively rewrites Verilog to improve post-synthesis timing, gated
  by sequential equivalence checking. Reproduced as the
  **`drrtl-baseline`** harness ([details](docs/drrtl_reference.md)).
* **[MasterRTL](https://github.com/hkust-zhiyao/MasterRTL)** (ICCAD'23) — a
  pre-synthesis PPA estimator built on the bit-level Simple Operator Graph
  (SOG). Reproduced as the **`rtlagent.proxy`** package
  ([details](docs/masterrtl_reference.md)) and used as the improved
  harness's fast inner-loop candidate ranker.

The originals depend on Synopsys Design Compiler, Formality/JasperGold and
commercial licenses. Everything here runs on **yosys + Icarus Verilog +
Python**, so the whole loop — synthesis, STA, formal equivalence, simulation,
optimization — works on a laptop or CI runner.

```
pip install anthropic openai scikit-learn
apt-get install yosys iverilog
```

## Quick start

```bash
cd agentic

# Synthesize a benchmark and see its timing report (per-cell critical paths)
python3 -m rtlagent.cli synth benchmarks/add_chain

# Run the MasterRTL-style SOG proxy (fast pre-synthesis PPA estimate)
python3 -m rtlagent.cli proxy benchmarks/add_chain

# Optimize with the improved harness using Claude
export ANTHROPIC_API_KEY=...
python3 -m rtlagent.cli optimize benchmarks/add_chain --backend anthropic:claude-sonnet-5

# ... or with GLM 5.2 (Zhipu API or any OpenAI-compatible server)
export GLM_API_KEY=...
python3 -m rtlagent.cli optimize benchmarks/add_chain --backend glm:glm-5.2
# local vLLM serving an open-weight model:
python3 -m rtlagent.cli optimize benchmarks/add_chain --backend "vllm:zai-org/GLM-5.2@http://localhost:8000/v1"

# Head-to-head: Dr.RTL baseline vs improved harness, same model, same budget
python3 -m rtlagent.cli eval benchmarks/* --backend anthropic:claude-sonnet-5 --rounds 6

# Offline self-test (no API key needed)
python3 tests/test_units.py && python3 tests/test_e2e_mock.py
```

## Architecture

```
rtlagent/
├── eda/          open-source EDA backend
│   ├── yosys.py      synthesis: yosys `synth -noalumacc` + ABC → liberty netlist
│   ├── sta.py        built-in static timing: WNS/TNS + per-cell critical paths
│   ├── equiv.py      SEC: yosys SAT temporal induction, BMC fallback
│   ├── sim.py        Icarus: testbenches + auto-generated lockstep random compare
│   └── metrics.py    Dr.RTL composite score (0.5·WNS + 0.35·TNS + 0.15·Area + penalty)
├── llm/          pluggable model backends
│   ├── anthropic_backend.py   Claude via the Anthropic SDK
│   ├── openai_backend.py      GLM / vLLM / OpenRouter / DeepSeek / Qwen (OpenAI-compatible)
│   └── mock_backend.py        deterministic offline backend for tests
├── proxy/        MasterRTL reproduction
│   ├── sog.py        SOG extraction (yosys techmap bit-blast) + std_PPA features
│   └── model.py      learned PPA proxy (sklearn GBM) with analytical fallback
├── harness/
│   ├── baseline.py   Dr.RTL loop reproduction (serial minors, full SEC each)
│   ├── agentic.py    RTLflow-Agent: the improved harness
│   ├── verify.py     staged verification: lint → lockstep sim → testbench → SAT SEC
│   ├── skills.py     skill memory w/ success tracking + per-design failure memory
│   └── prompts.py    analyzer / optimizer / repair / skill-extractor roles
├── eval.py       baseline-vs-agentic comparison runner
└── cli.py
benchmarks/       designs with self-checking testbenches + spec.json
```

## What the improved harness does differently (and why it wins)

The Dr.RTL reproduction (`--harness baseline`) is faithful to the published
loop: up to 10 major rounds × 5 serial minors, each minor doing
analyze → rewrite → **full synthesis** → **full SEC**, promoting the round's
best verified score, stopping after a round without improvement, with
word-level slack feedback only. `RTLFlowAgent` (`--harness agentic`) keeps
the same promotion discipline and scoring but changes the search:

| Dr.RTL weakness (measured from its repo)                       | RTLflow-Agent |
|---------------------------------------------------------------|---------------|
| 5 serial minors per round, each blocking on full EDA           | N candidates generated in parallel (diverse directives × temperatures) |
| Full synthesis + formal proof on every attempt (SEC pass rates as low as ~40% ⇒ ~half the EDA budget proves failures) | Staged triage: lint (~s) → **MasterRTL-style SOG proxy ranking** (~s) → only top-K reach synthesis; SEC last, after lockstep random simulation |
| SEC failure ⇒ attempt discarded, counterexample ignored        | Failure evidence (lint error, sim mismatch trace, SEC counterexample) feeds a one-shot **repair loop** |
| Greedy single lineage, no backtracking                         | Beam of top-k verified lineages; plateaued lineages get demoted |
| Word-level `startpoint→endpoint: slack` feedback only          | Full per-cell critical-path breakdown from the built-in STA |
| Static, manually-merged skill file; stateless sub-agents       | Skill success rates update online; failed transforms are remembered per design and excluded from prompts; new skills extracted in-loop |
| Orchestrator LLM does score arithmetic / JSON / file bookkeeping in-context | All bookkeeping is deterministic Python; the LLM only analyzes and writes RTL |

The scoring, promotion rule, stopping rule and verification-gate semantics
are identical between the two harnesses, so `eval` compares search
strategies, not scoring tricks. On the offline mock test the agentic harness
finds, formally proves and promotes an adder-tree rebalance on `add_chain`
(WNS −4.48 → −2.88 ns, area −2%) that the serial no-op baseline never reaches.

## Reproduction fidelity notes

* **Synthesis**: `yosys synth -noalumacc` + ABC mapping to a bundled generic
  liberty replaces DC `compile`. `-noalumacc` matters: without it yosys fuses
  adder chains into pre-balanced `$macc` implementations and RTL-level timing
  transforms become invisible — with it, the flow has the plain-`compile`
  sensitivity to RTL structure that Dr.RTL's premise depends on.
* **STA**: `rtlagent.eda.sta` computes arrival times over the mapped netlist
  with a fixed per-cell delay model — consistent and monotonic, which is what
  an optimization loop needs (not sign-off accuracy).
* **SEC**: yosys SAT temporal induction (proof) with BMC fallback replaces
  JasperGold `check_sec -prove`; candidates additionally pass auto-generated
  lockstep random simulation against the golden design, always vs **v0**
  (like Dr.RTL).
* **Score**: exactly Dr.RTL's `0.5·WNS_norm + 0.35·TNS_norm + 0.15·Area_norm`,
  `X_norm = (X − X_base)/|X_base|` on violation magnitudes, +0.5 penalty when
  area grows >10%, computed against the v0 baseline.
* **Proxy**: MasterRTL's SOG recipe (`proc; flatten; opt; fsm; opt; memory;
  opt; techmap; opt`), its published `std_PPA.json` operator constants and
  fanout-weighted analytical delay model; the learned layer bootstraps from
  the harness's own synthesis runs (every full synthesis is a free training
  sample) instead of a pre-collected commercial-tool dataset.

## Model support

| Spec string | Backend |
|---|---|
| `anthropic:claude-sonnet-5`, `anthropic:claude-opus-4-8` | Anthropic API (`ANTHROPIC_API_KEY`) |
| `glm:glm-5.2` | Zhipu GLM API (`GLM_API_KEY`, `GLM_BASE_URL` to switch z.ai/bigmodel) |
| `openai:<model>` | OpenAI API (`OPENAI_API_KEY`) |
| `vllm:<model>@http://host:8000/v1` | any local open-weight server |
| `openrouter:<vendor/model>` | OpenRouter (`OPENROUTER_API_KEY`) |
| `deepseek:...`, `qwen:...` | native OpenAI-compatible endpoints |
| `mock:` | deterministic offline backend (tests/CI) |

`RTLAGENT_BACKEND` sets the default spec.

## Adding a benchmark

Create `benchmarks/<name>/` with `design.v`, a self-checking `tb.v` that
prints `TEST PASSED`/`TEST FAILED`, and `spec.json`:

```json
{"name": "...", "top": "...", "files": ["design.v"], "testbench": "tb.v",
 "clock_period": 1.0, "description": "..."}
```

Pick a `clock_period` the baseline design *violates* — like Dr.RTL's
deliberately infeasible constraint, it keeps a WNS/TNS gradient alive for
the optimizer.
