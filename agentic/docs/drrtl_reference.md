# Dr.RTL Framework Specification

**Source**: https://github.com/hkust-zhiyao/Dr_RTL (default branch: `main`)
**Title**: "Dr.RTL: Autonomous Agentic RTL optimization through Tool-Grounded Self-Improvement" (HKUST zhiyao lab)
**Researched**: 2026-07-01, via GitHub web + raw.githubusercontent.com fetches.

Repository layout:

```
Dr_RTL/
├── CLAUDE.md                  # orchestrator rules (drives Claude Code main loop)
├── README.md
├── .claude/
│   ├── agents/
│   │   ├── rtl-timing-analyzer.md
│   │   ├── rtl-optimizer.md
│   │   ├── rtl-synthesis-evaluator.md
│   │   ├── rtl-opt-skill-extractor.md
│   │   └── rtl-opt-skill-extractor-per-design.md
│   └── skill/rtl-opt/
│       ├── skill.md           # merged cross-design skill library (~47 skills)
│       └── LICENSE.txt
├── rtl_dataset/               # 20 baseline designs (<name>.v0.v / .sv)
├── syn_flow/                  # agent-machine working dir
│   ├── rtl/                   # versioned RTL (starts with the 20 v0 baselines)
│   ├── design_all.json        # design metadata (top, clk, rst, filetype)
│   ├── run_remote.py          # SSH/SCP bridge to EDA machine
│   ├── add_design_remote.py   # register a new design on EDA machine
│   └── makefile               # clean: wipe log/history/output, delete non-v0 RTL
└── syn_flow_eda/              # EDA-machine side
    ├── run_design.py          # syn + LEC/SEC/sim + report parsing
    ├── design_all.json
    ├── scr/ {syn.tcl, sec.tcl, fm.tcl}
    ├── lib/                   # nangate.db (NanGate 45nm)
    ├── tb/  {DSP.v, LSTM.v}   # testbenches (LSTM uses sim instead of SEC)
    └── makefile               # clean / clean_all of tool droppings
```

---

## 1. Orchestrator workflow (CLAUDE.md)

CLAUDE.md is the orchestrator prompt for Claude Code itself. Near-verbatim content:

### Loop structure

```
For each major version (v0 to v9):
    Run 5 minor attempts (vX.1 to vX.5)
    Select best SEC-pass minor → Promote to next major

Stop after v10 is created
```

**Steps per minor**:
1. **ANALYZE**: `@agent-rtl-timing-analyzer`
2. **OPTIMIZE**: `@agent-rtl-optimizer`
3. **EVALUATE**: `@agent-rtl-synthesis-evaluator`
4. **RECORD**: Update `iter.json` with results and score

**After all 5 minors**:
5. **SELECT**: Best SEC-pass minor (lowest score)
6. **PROMOTE**: Rename to next major version
7. **UPDATE**: `history.json`

Note: CLAUDE.md specifies 5 minors/round; the per-design skill extractor and skill.md statistics reference **10 minors per round / 50 total minors per design**, so actual experiments appear to have been run with a 10-minor variant ("parallel exploration trajectory") at some point. The published orchestrator config says 5.

### Diversity strategy

The orchestrator chooses, per minor, at runtime:
- **Path selection**: top-K by slack, path range, endpoint clustering, high fanout, module-focused, random sample
- **Optimization focus**: combinational, sequential, mixed

It must ensure the 5 minors differ ("explore different optimization opportunities").

### Scoring formula (exact, lower = better)

```
score = 0.5 × WNS_norm + 0.35 × TNS_norm + 0.15 × Area_norm + penalty

WNS_norm  = (WNS  - WNS_baseline)  / |WNS_baseline|
TNS_norm  = (TNS  - TNS_baseline)  / |TNS_baseline|
Area_norm = (Area - Area_baseline) / Area_baseline

penalty = 0.5 if Area_norm > 0.10, else 0
```

Baseline = v0 metrics. WNS/TNS baselines are negative (constraints are deliberately infeasible, see §4), so improvement makes WNS_norm/TNS_norm negative. Score is computed by the orchestrator (RECORD step), not by a script — the LLM does the arithmetic and writes it into iter.json.

### Promotion rule
- Among the round's minors with `sec_status == "pass"`, pick the **lowest score**; copy/rename `<design>.vX.k.v` → `<design>.v(X+1).v`.
- SEC-fail minors get `score: null` and are never promoted.

### Stopping criteria (`end_reason` in history.json)
- `v10` created → `"max_major_reached"`
- A complete round with **no promotions** (no SEC-pass improvement) → `"no_improvement"`
  (README phrases this as "completing a round without improvement".)

### Agent rules (verbatim)
- Orchestrator delegates to agents, does NOT run synthesis directly
- Sub-agents have no memory between invocations
- Always optimize from current major version (best_version)
- Each minor is independent

### User command procedure
1. Initialize: Evaluate v0 (run synthesis on baseline), create history.json
2. Loop: 10 major rounds × 5 minors each
3. Select & Promote: best minor → next major
4. Report: best_version and final PPA

### Iteration record schema — `syn_flow/log/<design>.<version>.iter.json`

```json
{
  "design": "<design>",
  "base_version": "v0",
  "target_version": "v0.1",
  "diversity_strategy": {
    "minor_index": 1,
    "path_selection": "<orchestrator defined>",
    "optimization_focus": "<orchestrator defined>"
  },
  "wns_before": -0.45,
  "tns_before": -12.3,
  "area_baseline": 12000,
  "critical_paths": [...],
  "evaluation": {
    "sec_status": "pass",
    "wns_after": -0.32,
    "tns_after": -7.5,
    "area": 12200
  },
  "scoring": {
    "wns_norm": -0.289,
    "tns_norm": -0.390,
    "area_norm": 0.017,
    "area_penalty": 0,
    "score": -0.278
  }
}
```

### History schema — `syn_flow/history/<design>.history.json`

```json
{
  "design": "alu",
  "baseline": { "wns": -0.45, "tns": -12.3, "area": 12000 },
  "best_version": "v2",
  "best_ppa": { "wns": -0.18, "tns": -4.2, "area": 12350 },
  "end_reason": null,
  "major_rounds": [
    {
      "major_version": "v0",
      "minors": [
        { "version": "v0.1", "sec": "pass", "score": -0.245, "promoted": false },
        { "version": "v0.2", "sec": "fail", "score": null,   "promoted": false },
        { "version": "v0.3", "sec": "pass", "score": -0.298, "promoted": true }
      ],
      "promoted_to": "v1"
    }
  ]
}
```

---

## 2. Sub-agents (`.claude/agents/*.md`)

All are Claude Code sub-agent definition files with YAML frontmatter (`name`, `description`, `model`, `color`). Content below is verbatim or near-verbatim from the raw files.

### 2.1 rtl-timing-analyzer (model: **opus**, color: yellow)

> description: "Analyze RTL timing bottlenecks from synthesized timing reports. Dynamically selects critical paths, maps to RTL, identifies root causes."

"You are the **RTL Timing Analyzer** in the AgenticRTL framework. Your sole responsibility is to **diagnose why timing fails and where** — not how to fix it."

**Inputs**:
1. RTL source: `syn_flow/rtl/<design>.<best_version>.v`
2. Timing report: `syn_flow/output/<design>.<best_version>/timing_word.json`
3. Target version (from orchestrator, e.g. `v0.1`, `v1.2`)
4. Optional hint `"try_different_paths"`: skip paths from previous iterations
5. Previous iter.json files (if hint given)

Always analyze from the best (major) version; re-analyze every iteration.

**Path selection — decide K in [10, 25]**:
- Total paths: <50 paths → K=10; 50–150 → K=15; >150 → K=20–25
- Slack distribution: many paths within 0.1 ns of each other → increase K; one dominant path → lower K
- Complexity: more hierarchy → increase K

Normal: top-K by worst slack. With hint: read previous iter.json for this major version, skip paths analyzed in last 2 iterations, take next-K worst untried.

**Methodology**: (1) select K paths, rank most-negative-slack first; (2) RTL mapping — signal names, registers, logic structure (arithmetic/mux/control); (3) root-cause diagnosis — long combinational depth, wide fan-in/out, complex arithmetic, control-data coupling, reconvergent fanout; (4) amenability classification:

| Category | Description | Optimizer action |
|---|---|---|
| combinational | logic restructuring | can fix |
| sequential-safe | retiming, no latency change | can fix |
| sequential-unsafe | requires latency change | skip |
| out-of-scope | needs constraints/redesign | skip |

**Output** — writes/creates `syn_flow/log/<design>.<target_version>.iter.json` with `path_selection` metadata (`total_paths`, `k_selected`, `selection_reason`, `hint_applied`, `paths_skipped`) and `critical_paths[]` entries: `{id, slack, startpoint, endpoint, logic_structure, root_cause, amenability, optimization: null, result: null}`; `evaluation: null`.

**Hard constraints**: K in [10,25]; do NOT run any tools; output valid JSON.

### 2.2 rtl-optimizer (model: **opus**, color: blue)

> description: "Optimize RTL timing using learned skills or novel transformations. Functional correctness validated via SEC."

"Your role is to **improve timing** while preserving **functional correctness**."

**Inputs**:
1. RTL source: `syn_flow/rtl/<design>.<base_version>.v`
2. Iteration data with path analysis: `syn_flow/log/<design>.<target_version>.iter.json`
3. Target version
4. RTL Optimization skills: `/home/xxx/Dr_RTL/.claude/skill/rtl-opt/skill.md`

**Per critical path, choose ONE of**:
- **Option A — Apply Learned Skill**: match path characteristics to `recommended_strategies`, mark `skill_source: "learned"` (with `skill_confidence`)
- **Option B — Propose New Optimization**: novel transform, mark `skill_source: "proposed"`
- Decision: use learned when path matches a high/medium confidence strategy; propose when nothing matches or to explore; **always avoid** strategies in `anti_patterns`.

**Allowed optimizations**:
- Combinational: boolean simplification, common subexpression extraction, arithmetic tree balancing, mux restructuring, logic reassociation (or novel)
- Sequential: retiming (no latency change), register rebalancing, register duplication, FSM encoding changes (or novel)

**Forbidden**: add/remove pipeline stages; change module interfaces; break architectural contracts; remove resets or clocking; use anti-pattern strategies.

**Outputs**: full optimized RTL at `syn_flow/rtl/<design>.<target_version>.v` (whole file, not a diff), plus per-path `optimization` records in iter.json, e.g.:

```json
{ "id": 1, "optimization": { "applied": true, "type": "combinational",
  "strategy": "tree balancing",
  "detail": "rebalanced adder tree to reduce depth from 4 to 3",
  "skill_source": "learned", "skill_confidence": "high" } }
{ "id": 3, "optimization": { "applied": false, "type": "skipped",
  "reason": "anti-pattern: fsm encoding" } }
```

**Behavioral contract**: load cross-design skills if available; process paths worst-slack first; never change latency; do NOT predict SEC or PPA results; record `skill_source` per optimization.

### 2.3 rtl-synthesis-evaluator (model: **haiku**, color: green)

> description: "Execute remote RTL synthesis and sequential equivalence checking (SEC) by running a single Python command. This agent performs execution only and does not read, write, or summarize any results."

Full body (near-verbatim):

```
You are an RTL Synthesis Evaluator.

## Input
- design_name
- design_version

## Execution (ONLY allowed action)
Run exactly the following command, and nothing else:
    bash -c "cd /home/xxx/Dr_RTL/syn_flow && python3 run_remote.py <design_name> <design_version>"
Example: python3 run_remote.py UART v1

## Strict Rules (Non-Negotiable)
- Do NOT read any files (logs, reports, JSON, text, or otherwise)
- Do NOT write or modify any files
- Do NOT summarize, interpret, or analyze results
- Do NOT run any additional commands
- Do NOT retry, debug, or alter the workflow
- Do NOT print logs unless the command itself fails
```

(The orchestrator itself reads the downloaded `output/` JSONs afterward for the RECORD step.)

### 2.4 rtl-opt-skill-extractor (model: **opus**, color: purple)

> description: "Extract cross-design RTL optimization skills from optimization trajectories. Generates reusable knowledge for future optimizations."

**Inputs**: `raw_memory/attempt_*/history/<design>.history.json`, `raw_memory/attempt_*/log/<design>.*.iter.json`, `raw_memory/attempt_*/rtl/<design>.*.v` (compare versions of promoted iterations), and per-design summaries `skill/attempt_*/*.skills.json`.

**Methodology**:
1. Collect successes: SEC passed AND timing improved (promoted); record path characteristics, optimization applied, deltas (WNS/TNS/area)
2. Collect failures: SEC fail OR timing degraded; what was attempted and why it failed
3. Pattern extraction: group by path type (arithmetic/mux/control/FSM), root cause, strategy; compute success rate, avg improvement, common failure patterns
4. Skill generation for patterns with **≥3 occurrences and >60% success**: rule + applicability conditions + expected improvement + risks

**Output** — `skill/rtl-opt-skills.md`, markdown with sections: High-Confidence Strategies (>80% success), Medium-Confidence (50–80%), Low-Confidence/Risky, Anti-Patterns (avoid), a "Path Type → Strategy Mapping" table (characteristic / strategy / confidence), and a Statistics table (strategy / attempts / successes / rate / avg WNS improvement). Each entry has: Applies to, Strategy, Expected improvement (WNS +X%, TNS +Y%), Area impact, Risk, Evidence (design.version list).

**Hard constraints**: only patterns with ≥3 occurrences; distinguish confidence levels; include successes AND failures; do NOT invent patterns without evidence; always cite evidence; valid markdown.

Invocation note at the bottom of the file: `@agent-rtl-opt-skill-extractor analyze all designs in syn_flow/`

### 2.5 rtl-opt-skill-extractor-per-design (model: **opus**, color: green)

> description: "Extract optimization patterns from a single design's parallel exploration trajectory."

Inputs: design name + same `raw_memory/attempt_*` trees. Per major round: collect **all 10 minor attempts**, identify promoted minor, compare promoted vs non-promoted strategies. Per minor: diversity strategy used, path characteristics, optimization, result (SEC/score/deltas), promoted?. Groups patterns by path type + root cause + strategy; computes occurrences, promotions, SEC pass rate, avg score, avg WNS/TNS/area improvement.

- **Winning strategies**: promoted ≥1 time, OR SEC pass rate ≥80% AND avg score < −0.1
- **Anti-patterns**: SEC fail rate ≥50%, OR never promoted AND avg score > 0
- **Diversity ranking**: rank path-selection methods by promotion rate and avg SEC-pass score

Output: `skill/attempt_*/<design>.skills.json` with `summary {total_major_rounds: 10, total_minors: 50, sec_pass_count, promotions}`, `patterns[]` (with evidence versions and promoted flags), `anti_patterns[]`, `diversity_ranking[]`. Hard constraints: single design only; valid JSON; evidence for every pattern; track promotion status for all minors.

---

## 3. Skill pack — `.claude/skill/rtl-opt/skill.md`

Frontmatter:
```yaml
name: rtl-opt
description: Critical path patterns with corresponding optimization strategies.
license: Complete terms in LICENSE.txt
```

Intro: "This file merges and normalizes the uploaded skill libraries into one comprehensive reference. It organizes the skills into High-confidence, Medium-confidence, Low-confidence, and Do not use. Each skill is written in the format: `<pattern, strategy, example>`. For every example, both before and after Verilog snippets are included." (~8,500 words; ~47 skills, every one with a before/after Verilog snippet.)

Section order: High-Confidence Strategies (>80%) → Medium-Confidence (50–80%) → Low-Confidence/Risky → Anti-Patterns → Path Type to Strategy Mapping → Strategy Success by Design Type → Statistics → Design-Specific Observations → Lessons Learned → Recommended Workflow → RTL Optimization Skill Summary (skills 1–47 in four tiers) → Practical usage notes.

### Example skill (first entry, verbatim structure)

Title: `<repeated comparisons / repeated control checks, pre-compute shared condition wires and reuse them, example>`
- Pattern: "repeated `(state == X)`, `(cmd == Y)`, `(count == Z)` or repeated shared condition fragments across branches."
- Strategy: "extract named wires once, then reuse them in `always` / `assign` logic. Very safe and consistently effective for FSM decode, counters, and control fanout."

Before:
```verilog
always @(*) begin
  if (state == IDLE && cmd == START)      next_state = START;
  else if (state == IDLE && cmd == STOP)  next_state = STOP;
  else                                    next_state = state;
end
```
After:
```verilog
wire state_is_idle = (state == IDLE);
wire cmd_is_start  = (cmd == START);
wire cmd_is_stop   = (cmd == STOP);
wire go_start      = state_is_idle & cmd_is_start;
wire go_stop       = state_is_idle & cmd_is_stop;
always @(*) begin
  if (go_start)      next_state = START;
  else if (go_stop)  next_state = STOP;
  else               next_state = state;
end
```

### Named strategies (with recorded stats)

High-confidence (>80%): 1. One-hot pre-decode for control signals (92%, WNS +5–15%; evidence cpu_fsm.v0.2, SPI.v0.5, UART.v0.4, DSP.v0.4) · 2. Condition pre-computation with wire extraction (89%) · 3. Register duplication for fanout reduction (88%; router.v0.2 WNS −0.52→−0.47, TNS −290→−263) · 4. FSM output registration (90%) · 5. Input signal registration/pipelining (86%).

Medium (50–80%): 6. Late mux-select with unconditional computation (67%) · 7. Mux-before-adder restructuring (75%; vending_machine.v0.2: 33% area reduction; WNS +30–60%, area −20–35%) · 8. Hierarchical case decomposition for large lookup tables (80%; pcie.v0.9: WNS −0.79→−0.48, area −42%) · 9. Logic tree balancing in GF arithmetic (63%; datapath/AES S-box) · 10. CSE (70%) · 11. One-hot FSM encoding with direct bit equations (63%, area −30% to +100%).

Low-confidence/risky: 12. Parallel evaluation with logic flattening (33%; ticket_machine.v0.1 SEC FAILED despite 39% WNS gain) · 13. Count-down counter restructuring (0%!) · 14. Explicit intermediate wire decomposition (83% pass, minimal gain) · 15. Aggressive mux tree restructuring.

Anti-patterns (avoid): A1 changing counter direction (UART.v0.1/v0.3 SEC FAILED) · A2 aggressive priority-chain flattening (loses if-else priority semantics) · A3 pre-registering mux selector signals (adds control latency; vending_machine.v0.4 SEC FAILED) · A4 modifying memory array addressing · A5 optimizing register self-loop (clock-to-Q+setup constraint-only) paths · A6 changing LFSR feedback/polynomial.

The extended "Skill Summary" enumerates 47 skills: 1–12 high (pre-compute condition wires, hierarchical wire factoring, one-hot pre-decode, direct bit indexing, CSE-to-named-wire, hoist shared subexpression, duplicate register copies, replicate equivalent wires, carry-select blocks, borrow lookahead for decrement, power-of-two bit-select, register FSM boundary outputs), 13–28 medium (parallel branch computation, branch+late-mux, mux-before-adder, parallel condition flattening, case→AND-OR equations, balanced reduction trees, multi-level mux restructuring, multi-operand adder trees, hierarchical ROM sub-decoders, GF stage rebalancing, constant-mult shift-add, compare-then-mux, FSM output grouping, timing-state pre-decode, intermediate wire guidance, explicit truncation boundaries), 29–34 low, 35–47 "do not use" (count direction rewrite, priority flattening w/o mutual exclusion, selector pre-registration, cross-module control pre-registration, operand width reduction, corner-changing algebra, arithmetic fusion, LFSR changes, memory addressing changes, self-loop paths, boundary-removing simplification, semantic-changing comparison reordering, blanket tree balancing).

Statistics table (attempts/successes/rate/avg WNS gain), e.g. one-hot pre-decode 12/11 92% +8%; condition pre-computation 18/16 89% +5%; mux-before-adder 4/3 75% +40%; count direction change 4/0 0%.

Design-specific SEC pass rates (x/50 minors): SPI 98%, FIFO 96%, pcie 96%, cpu_fsm 94%, datapath 90%, vending_machine 76%, DSP 74%, router 70%, LSTM 56%, ticket_machine 50%, UART 48% ("counter logic very sensitive to restructuring"), cpu_pipe 44%, simple_spi 38% (5/13).

Recommended workflow in skill.md: (1) start with low-risk strategies #1–#5; (2) measure before escalating risk; (3) module-focus when a clear bottleneck exists; (4) avoid anti-patterns (counter direction, priority flattening, selector pre-registration — "frequently fail SEC"); (5) accept architectural limits (multipliers, memory arrays, LFSR feedback "require clock tree optimization, not RTL changes"); combine strategies when individual ones plateau.

---

## 4. EDA flow and agent↔EDA-machine protocol

### 4.1 Agent side — `syn_flow/run_remote.py`

`python3 run_remote.py <design_name> <design_version>` (this is the single command the evaluator agent runs). Uses **paramiko + scp**. Hardcoded (redacted `'xxx'`) host/username/password config; 1-hour timeout.

Protocol per evaluation:
1. SSH connect to EDA host.
2. **Upload**: `./rtl/<design>.<version>.<tpe>` (the RTL file, tpe = `v`|`sv`) → `/home/xxx/Dr_RTL/syn_flow/rtl/` on the EDA machine; also uploads `design_all.json`.
3. **Execute remotely**: `bash -c 'source ~/.bashrc && cd /home/xxx/Dr_RTL/syn_flow && python3 run_design.py <design> <version>'`, streaming stdout live; non-zero exit → `sys.exit(1)`.
4. **Download**: remote `output/<design>.<version>/` → local `./output/` (so agents read `syn_flow/output/<design>.<version>/{PPA_report.json, timing_word.json, SEC_result.txt}`).
5. Close connection.

`design_all.json` maps design → `[top_module, clock_name, reset_name, filetype]` (see §5). `add_design_remote.py` registers a new design entry on the remote machine over SSH (default clock_period arg 2.0, though the actual TCL clock is fixed).

### 4.2 EDA side — `syn_flow_eda/run_design.py`

Functions: `get_design_config, bit_2_word, run_syn, run_lec, run_sim, run_sec, parse_LEC_report, parse_sim_report, parse_sec_report, parse_timing_report, parse_PPA_report, get_report_sec, get_report_sim, run_design`.

Flow (`run_design`): `run_syn()` always; then **if design == LSTM**: `run_sim()` + `get_report_sim()` (VCS testbench simulation, "PASS" grep — SEC presumably intractable for LSTM); **else**: `run_sec()` + `get_report_sec()`. `run_lec()` (Formality RTL-vs-netlist) exists but is commented out of the main flow.

**Synthesis (`run_syn`)**: instantiates `scr/syn.tcl` by string-replacing placeholders (`design_name_here`, `design_top_here`, `design_clk_here`, `design_tpe_here`...), runs `dc_shell -f <tcl> > log/syn_<design>.<ver>.log`. Key TCL contents:
- `target_library = nangate.db` (NanGate 45nm), `search_path ./lib ./input`
- `analyze -format {v→verilog | sv→sverilog} -recursive -autoread ./rtl/<design>.<ver>.<tpe> -top <TOP>` then `elaborate`
- **Constraints: `create_clock -period 0.1` and `set_max_delay 0.1 -from all_inputs -to all_outputs`** — a deliberately infeasible 0.1 ns target so every design has negative WNS/TNS to normalize against
- `compile` (NOT compile_ultra), `ungroup -all -flatten`
- Reports: `report_timing -tran -net -input -max_paths 100000 > reports/<d>.<v>/timing.rpt`, `report_area`, `report_power`, `report_qor`
- Writes `netlist/<d>.<v>.syn.v` + SDF

**SEC (`run_sec`)**: instantiates `scr/sec.tcl`, runs `jaspergold -sec -batch -tcl <tcl> > log/sec_<d>.<v>.log`. sec.tcl (Cadence JasperGold SEC app):
```
check_sec -analyze -spec -sv ./rtl/<design>.v0.<tpe>       # golden = original v0 RTL
check_sec -analyze -imp  -sv ./rtl/<design>.<ver>.<tpe>    # implementation = optimized RTL
check_sec -elaborate -spec/-imp -top <TOP> -disable_auto_bbox
check_sec -setup ; check_sec -map -auto
clock <clk> ; reset <rst>
check_sec -gen ; check_sec -prove -strategy proof
```
So SEC is **RTL-vs-RTL against v0** (not against the immediate parent version). Pass detection: `parse_sec_report` greps the log for a line matching regex `^proven$` → writes `output/<d>.<v>/SEC_result.txt` ("PASSED"/"FAILED"). A missing reset in design_all.json aborts SEC.

**LEC (`run_lec`, unused in main flow)**: Formality `fm_shell -f fm.tcl`; fm.tcl compares `netlist/<design>.v0.syn.v` (reference) vs `netlist/<design>.<ver>.syn.v` (implementation) with `match; verify`; pass = "SUCCEEDED" after "Verification Results" in the log.

**Report parsing → data returned to agents** (`output/<design>.<version>/`):
- `PPA_report.json` = `{"Area", "WNS", "TNS", "Power"}` — Area from `qor.rpt` "Design Area:", WNS from "Critical Path Slack:", TNS from "Total Negative Slack:", Power from `power.rpt` "Total Dynamic Power ="
- `timing_word.json` = `{ "startpoint -> endpoint": worst_slack, ... }` — parsed from timing.rpt (Startpoint/Endpoint/slack lines); `bit_2_word()` collapses per-bit register names (e.g. `count_reg[3]`) to word-level names keeping the min slack per word-level path. This word-level slack map is the *entire* timing view the analyzer agent gets (no cell-by-cell path detail).
- `SEC_result.txt` = PASSED/FAILED

### 4.3 Makefiles
- `syn_flow/makefile`: `clean` = `rm -rf ./log/* ./history/* ./output/*` and delete every `rtl/*.v`/`*.sv` **except** `*.v0.*` (resets a run to baselines).
- `syn_flow_eda/makefile`: `clean` removes tool droppings (`*.log csrc simv* *.key *.vpd DVEfiles coverage *.vdb *.svf *.rpt *.tcl` ...), `clean_all` additionally wipes `netlist/ log/ reports/` etc.

---

## 5. rtl_dataset (20 designs)

`design_all.json` format: `"name": [top_module, clock, reset, filetype]`.

| Design | Top module | Clk / Rst | File | Size |
|---|---|---|---|---|
| vending_machine | vending_machine | clk / reset | .v | 128 lines, 3.7 KB |
| ticket_machine | ticket_machine | clk / clear | .v | small FSM |
| LSTM | lstm_cell | clk / rst | .v | 135 lines, 3.1 KB (sim-verified, not SEC) |
| DSP | DSP | clk / rstA | .v | small/medium (has tb/DSP.v) |
| simple_spi | simple_spi_top | clk_i / rst_i | .v | small (OpenCores) |
| cpu_fsm | mini_cpu | clk / rst | .v | small |
| FIFO | fifo | clk_in / rst | .v | small |
| SPI | spi | clk / rst | .v | small |
| UART | uart_top_design | clk / rst | .v | 447 lines, 11 KB |
| controller | control_unit | clk / rst_n | .v | small |
| router | router_top | clk / resetn | .v | medium |
| cpu_pipe | dcpu16_cpu | clk / rst | .v | 927 lines, 23.7 KB |
| pcie | top | clk / rst | .v | 923 lines, 39.9 KB |
| datapath | datapath | clk / rst_n | .v | medium (GF/AES-style arithmetic) |
| i2c | i2c_master_top | wb_clk_i / wb_rst_i | .v | medium (OpenCores WISHBONE) |
| tv80 | tv80s | clk / reset_n | .v | 4616 lines, 121 KB (Z80 core; largest) |
| aes | key_expansion_128aes | clk / rst_async_n | .sv | 374 lines, 11 KB (only SV design) |
| communication | sync_serial_communication_tx_rx | clk / reset_n | .v | small |
| arm_cpu1 | arm9_compatiable_code | clk / rst | .v | 1870 lines, 54.5 KB |
| arm_cpu2 | risclite_mx | clk / rst | .v | 1450 lines, 33 KB |

Range: ~100-line toy FSMs up to a ~4.6 K-line Z80. Single-file designs (one .v/.sv per design), copied identically into `rtl_dataset/` and `syn_flow/rtl/` as `<name>.v0.<tpe>`.

---

## 6. syn_flow directory layout during a run

```
syn_flow/
├── rtl/
│   ├── <design>.v0.v        # baseline (only files kept by make clean)
│   ├── <design>.v0.1.v ... <design>.v0.5.v   # round-0 minors (agent-written)
│   ├── <design>.v1.v        # promoted copy of best v0.x
│   ├── ...
│   └── <design>.v10.v       # terminal version (CLAUDE.md example shows v5 as "final")
├── log/<design>.<version>.iter.json     # one per minor (analyzer creates, optimizer + orchestrator update)
├── history/<design>.history.json        # orchestrator-maintained
└── output/<design>.<version>/           # downloaded from EDA machine per evaluation
    ├── PPA_report.json
    ├── timing_word.json
    └── SEC_result.txt
```

For skill extraction, completed runs are archived as `raw_memory/attempt_*/{history,log,rtl}/...` and extractor outputs go to `skill/attempt_*/<design>.skills.json` and `skill/rtl-opt-skills.md`; the curated merged result is committed at `.claude/skill/rtl-opt/skill.md`.

Versioning: `vX` = major (best-so-far), `vX.k` = minor attempt k on top of vX. Only SEC-pass minors are eligible; promotion = file copy/rename to `v(X+1)`. Every minor of every round re-synthesizes from scratch on the EDA machine.

---

## 7. LLM / CLI

- Runs on **Claude Code** (Anthropic CLI). CLAUDE.md is the standard Claude Code project memory driving the orchestrator; sub-agents are standard `.claude/agents/*.md` definitions invoked as `@agent-<name>`; the skill pack sits under `.claude/skill/`.
- Per-agent model pinning via frontmatter: analyzer/optimizer/both extractors = **opus**; synthesis-evaluator = **haiku** (it only shells out one command).
- The orchestrator (main Claude Code session, i.e. the default/session model) does scoring math, selection/promotion, iter.json/history.json bookkeeping, and diversity-strategy assignment itself.
- Launch: user simply asks Claude Code to optimize a design ("User Command" section of CLAUDE.md); skill extraction is launched manually: `@agent-rtl-opt-skill-extractor analyze all designs in syn_flow/`.
- EDA machine access is via hardcoded SSH credentials in run_remote.py (`'xxx'` placeholders in the public repo); paths hardcode `/home/xxx/Dr_RTL/syn_flow`.

---

## 8. Weaknesses an improved harness could exploit

1. **Fully serial exploration.** The 5 (or 10) minors per round run strictly one-after-another, each blocking on a full remote synthesis + JasperGold proof. All minors branch from the same base version, so they are embarrassingly parallel — a harness that synthesizes/proves N candidates concurrently (multiple dc_shell/jaspergold jobs or license-queued batch) gets a ~5–10x wall-clock win with zero algorithmic change.

2. **Full synthesis + full SEC on every attempt, no cheap pre-filter.** No lint/compile smoke test, no fast incremental timing estimate, no quick BMC/simulation sanity check before the expensive `check_sec -prove`. Given design-level SEC pass rates as low as 38–48% (UART, simple_spi, cpu_pipe), roughly half the EDA budget on hard designs is burned proving failures that a 30-second bounded-equivalence or lint pass would have rejected. An improved harness can triage: syntax/elaboration check → fast sim diff / BMC on a few hundred cycles → only then full SEC on survivors.

3. **Greedy hill-climbing with immediate discard.** Only the single best SEC-pass minor is promoted; all other passing variants (and their diffs) are thrown away rather than combined. Improvements are often on disjoint paths — merging compatible edits from multiple passing minors, or maintaining a small Pareto front (WNS vs area) / beam of k parents, dominates single-lineage greedy search. There is also no backtracking: a locally-good promotion that plateaus can't be revisited.

4. **No retry/repair loop on failure.** The evaluator is deliberately fire-and-forget ("Do NOT retry, debug"), and a SEC fail just scores null. The counterexample/unmapped-point information in the JasperGold log is never fed back to the optimizer for a repair attempt — a cheap "fix this SEC counterexample" inner loop would recover many near-miss transforms.

5. **Impoverished timing feedback.** Agents only see `timing_word.json`: word-level `startpoint -> endpoint : slack` pairs. No per-cell path breakdown, no arrival/required times, no fanout counts, no net delays, no hierarchy — the analyzer's "root cause" diagnosis is essentially LLM guesswork from RTL reading. Parsing full `report_timing` path detail (which is already generated with `-tran -net -input -max_paths 100000`!) and feeding structured path segments would ground the diagnosis.

6. **Unrealistic, static constraints.** Fixed 0.1 ns clock + `set_max_delay 0.1` on all I/O paths makes every path violate; WNS is dominated by the single longest path (often an unfixable multiplier/memory, per the skill file's own anti-patterns A4–A6), so many rounds chase structurally unoptimizable paths. Plain `compile` (not `compile_ultra`, no retime/incremental) also leaves synthesis QoR on the table and adds noise: some "RTL wins" may just be synthesis-seed variance. A better harness would use per-design achievable clocks, `compile_ultra`, and repeat-synthesis noise estimation before crediting a transform.

7. **LLM-side bookkeeping is fragile.** The orchestrator computes the score arithmetic, edits JSON, renames files and enforces stopping rules in-context, over 50+ iterations — long-horizon context drift, arithmetic slips, and JSON corruption are likely. A thin deterministic driver (script does scoring/promotion/version control; LLM only analyzes/edits RTL) removes this whole failure class.

8. **Stateless sub-agents, coarse memory.** Sub-agents have no memory between invocations; cross-attempt learning only enters via the static, manually merged skill.md (skill extraction is offline/manual, not in-loop). Within a run, the only adaptation is the "try_different_paths" hint. An improved harness can do online skill updating, per-design memory of failed transforms (avoid re-proposing the same SEC-failing edit), and use the per-design extractor's diversity-ranking to bias later rounds.

9. **Diversity is prompt-level, not enforced.** "Orchestrator should ensure diversity" is a soft instruction; nothing verifies the 5 minors actually differ (same skill applied 5x is possible). Explicit strategy assignment + diff-similarity checks would enforce genuine exploration.

10. **Scoring quirks.** Normalizing by |baseline| makes scores incomparable across designs and unstable when baseline TNS is small; the 0.5 area penalty is a cliff (10.1% area growth is as bad as huge growth, 9.9% is free); power is measured but ignored. SEC compares against v0 each time (good for soundness) but score compares against baseline rather than parent, so a round can be "promoted" while regressing relative to the parent only if the LLM mis-selects — the rule "lowest score" vs parent's score is not explicitly checked (promotion of a minor worse than its own base appears possible if all minors regress but one still scores below 0... actually the no-improvement guard depends on the orchestrator noticing; nothing programmatic prevents promoting a worse-than-parent variant).

11. **Single-file, single-clock designs only.** The flow assumes one RTL file, one clock, one reset (SEC exits if reset is missing); no multi-clock, no SDC beyond the toy constraint, no hierarchy preservation (`ungroup -all -flatten`). LSTM silently falls back to a "grep PASS" simulation — a much weaker correctness oracle.

12. **Security/robustness nits**: hardcoded SSH password in cleartext (redacted in repo), `AutoAddPolicy`, `os.system` shell interpolation of design names, and `echo '<json>' >` for remote config writes.
