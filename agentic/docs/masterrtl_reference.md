# MasterRTL — Detailed Reproduction Spec

Source: https://github.com/hkust-zhiyao/MasterRTL (default branch: `main`; repo is archived-in-spirit — README says it is no longer maintained, superseded by [RTL-Timer](https://github.com/hkust-zhiyao/RTL-Timer)).
Paper: "MasterRTL: A Pre-Synthesis PPA Estimation Framework for Any RTL Design", Fang, Lu, Liu, Zhang, Xu, Wills, Zhang, Xie — ICCAD 2023 (arXiv:2311.08441; TCAD 2024 extension: "Transferable Presynthesis PPA Estimation for RTL Designs").

Repository layout:

```
MasterRTL/
├── ys_script/        # Step 1: Yosys RTL -> SOG (or word-level AST) Verilog
│   ├── run_TinyRocket_sog.ys
│   ├── run_TinyRocket_ast.ys
│   └── clean_vlg.py
├── vlg2ir/           # Step 2: Pyverilog AST -> graph pickle
│   ├── auto_run.py, analyze.py, AST_analyzer.py, DG.py, logicGraph.py, graph_stat.py
├── preproc/
│   ├── timing/delay_propagation.py   (+ symlinked DG.py/logicGraph.py/graph_stat.py)
│   └── power/tr_propagate.py, design_hier.json
├── feature_extract/
│   ├── timing/feature_extra_graph_STA.py, train_path_rfr.py, pred_slack_calibration.py, pred_slack_lst/
│   ├── power/feature_extra_graph_pwr.py, feature_extra_module_pwr.py
│   └── area/feature_extra_graph_stat.py
├── ML_model/
│   ├── train/train.py, preprocess.py
│   ├── infer/infer.py, preprocess.py
│   ├── saved_model/, saved_data/
├── example/          # end-to-end demo dirs: verilog/, ast/, sog/, module/, timing_dag/, power_dag/, feature/, label/
├── pyverilog/        # vendored Pyverilog parser
└── std_PPA.json      # per-operator area / power / timing constants (NanGate45-derived)
```

Note: `DG.py`, `logicGraph.py`, `graph_stat.py` under `preproc/*` and `feature_extract/*` are **symlinks** to the `vlg2ir/` originals (raw fetch returns the literal target path `../../vlg2ir/graph_stat.py`).

---

## 1. Simple Operator Graph (SOG) representation

### 1.1 How RTL is converted — Yosys, then Pyverilog

**Tooling:** standard **Yosys** (no custom passes) writes a bit-blasted Verilog netlist; then the vendored **Pyverilog** parser + a custom `AST_analyzer` build the graph. There is no direct Yosys→graph path; the graph is always built by re-parsing the Yosys-emitted Verilog.

**Exact Yosys script for SOG** (`ys_script/run_TinyRocket_sog.ys`):

```
read  -verific
read_verilog ../example/verilog/TinyRocket/plusarg_reader.v
read_verilog ../example/verilog/TinyRocket/chipyard.TestHarness.TinyRocketConfig.top.v

# elaborate design hierarchy
hierarchy -check -top Rocket

# the high-level stuff
proc;
flatten;
opt; fsm; opt; memory; opt;

# mapping to internal cell library
techmap; opt;
write_verilog ../example/verilog/TinyRocket_sog.v
```

`techmap` maps everything to Yosys' internal single-bit gate library, so the written Verilog contains only 1-bit simple operators (AND/OR/NOT/XOR/MUX expressions and DFF `always` blocks). This is the "bit-level SOG".

**Word-level baseline ("AST" mode)** (`ys_script/run_TinyRocket_ast.ys`) — same but stops before techmap:

```
hierarchy -check -top Rocket
proc
flatten
memory
write_verilog ../example/verilog/TinyRocket_ast.v
```

**Cleanup** (`ys_script/clean_vlg.py`): removes Yosys attribute annotations matching `\(\*(.*)\*\)` and blank lines from the written Verilog (Pyverilog chokes on `(* ... *)`).

### 1.2 Graph construction (`vlg2ir/`)

- `auto_run.py` → calls `python3 analyze.py <design>_<cmd>.v -N <design> -C <cmd> -O ../example/<cmd>/` where `cmd ∈ {ast, sog}`.
- `analyze.py`: `pyverilog.vparser.parser.parse(filelist)` → AST → `AST_analyzer(ast).AST2Graph(ast)` → `graph.graph2pkl(...)` producing two pickles:
  - `<design>_<cmd>.pkl` — `defaultdict(list)` adjacency (**edge direction: consumer → producer**, i.e. `graph[node]` lists its *fan-in*; the code consistently uses `in_degree` as "fanout" and `successors` as "fanin").
  - `<design>_<cmd>_node_dict.pkl` — `{name: Node}`.

**Node class** (`vlg2ir/DG.py`): fields `name, type, width, father, path, tr (toggle rate, init None), t1 (static prob, init 0.5)`; methods `update_width/delay/fanout`, `update_AT` (longest-path arrival-time propagation), `finish_AT` (returns (startpoint,endpoint) pair, path node list, AT), `add_tr/add_t1`.

**Node types** produced by `AST_analyzer`:

| type | meaning / naming |
|---|---|
| `Input`, `Output`, `Inout` | ports |
| `Reg` | registers (become DFFs) |
| `Wire` | eliminated (collapsed) before saving |
| `Constant` | named `Constant<k>` |
| `Operator` | named `<Op><k>`, e.g. `And12`, `Or3`, `Xor7`, `Mux5`, `Cond9`, `Plus2`… (op recovered later by regex `([A-Z][a-z]*)(\d+)`) |
| `UnaryOperator` | `Unot<k>`, `Ulnot<k>`, `Uand`, `Uor`, `Uxor`, `Uminus`… |
| `Concat`, `Repeat` | width-0 structural ops |
| `Pointer` | bit-select `name.PTR<i>`, width 1, `father` = base signal |
| `Partselect` | `name.PS<msb>_<lsb>`, `father` = base signal |

Key `AST_analyzer` behaviors:
- `IfStatement` / `CaseStatement` (also Casez/Casex/UniqueCase) → explicit `Mux<k>` `Operator` nodes; if-without-else = no mux; if/else = one mux; else-if chains = recursion (multiple muxes); each case item gets its own mux.
- Verilog functions are inlined (`func_call` substitutes formal inputs).
- `cal_node_width()` iteratively assigns missing widths as `max(width of fan-in neighbors)`.
- `eliminate_wires()` repeatedly splices out `Wire` nodes (connect consumer directly to the wire's driver).
- `add_parent_edge()` adds edge `Reg-father → Pointer/Partselect-child`.

In SOG mode the operator alphabet effectively collapses to **{And, Or, Unot/Ulnot, Xor, Mux/Cond, Concat} + DFF (Reg)** — the paper's "single-bit simple operators". In `ast` (word-level) mode the full Pyverilog operator set appears (Plus, Minus, Times, Divide, Mod, LessThan, Sll, Sra, Eq, …), which is why `std_PPA.json` carries constants for all of them.

### 1.3 Per-operator constants — `std_PPA.json` (full contents)

Six sections: `area_seq`, `area_comb`, `stat_pwr`, `dyn_pwr`, `dyn_pwr_all`, `timing`. Values (NanGate45-flavored, area in µm², timing in ns):

- `area_seq`: `DFF: 4.522`
- `area_comb` (per bit): And/Land/Or/Lor/Uor/Uand 1.064; Xor/Xnor/Uxor 1.596; Unor/Unot/Ulnot 0.798; Cond/Case/Mux 1.862; Plus/Minus/Uminus 4.256; Times 37.5; Divide 40; Mod 35; LessThan/GreaterThan/LessEq/GreaterEq 35; Sra/Sla/Sll/Srl 3; Eq/Concat/Repeat/Than 0
- `stat_pwr`: DFF 0.07911; And 0.02507; Xor 0.03616; Or 0.02269; Unot/Ulnot 0.106; Cond/Mux/Case 0.03593; Plus/Minus 0.07576; Times/Divide/Mod 0.1; Sll etc. 0.03; comparators 0.3; Eq/Concat 0
- `dyn_pwr` (used by area/power features; SOG ops only): DFF 3.1, And 3.1, Or 3.1, Ulnot/Unot 1.8, Xor 2.45, Mux/Cond 2.6, Concat 0
- `dyn_pwr_all`: full word-level table (DFF 3.98, And 5.2, Or 2.71, Unot 4.61, Xor 2.43, Cond 3.38, Plus 4.95, Times 37.5, …)
- `timing`: `freq: 2` (GHz), `clk_unc: 0.05`, `lib_setup: 0.032`, `input_delay: 0`, `output_delay: 0`, per-op delays: DFF 0.1187, And 0.0496, Or 0.0323, Unot/Ulnot 0.0328, Mux/Cond 0.0498, Xor 0.0882, Concat 0

---

## 2. Circuit preprocessing (`preproc/`)

### 2.1 Timing: DAG conversion + analytical delay init (`preproc/timing/delay_propagation.py`)

1. **Register/IO splitting** (`graph_update` / `node_split`): every node of type `Reg`, `Input`, `Output` (and `Pointer`/`Partselect` children whose father is one of these) is split into `<name>_Q_` (receives all predecessor edges = timing **endpoint**) and `<name>_CK_` (sources all successor edges = timing **startpoint**); original node removed. Asserts `nx.is_directed_acyclic_graph`.
2. **Analytical node delay** (`get_node_delay_init`): `fanout = g.in_degree(name)` (remember reversed edges), and
   - Input/Output/Wire/Constant/Concat/Inout: delay 0
   - Operator/UnaryOperator: `delay = fanout * w` with **w = 0.42 (Mux/Cond), 0.42 (And), 0.27 (Or), 0.27 (Unot/Ulnot), 0.74 (Xor)**; Concat 0
   - Reg (and Pointer/Partselect of a Reg): `delay = fanout * 1.0`
3. Outputs to `example/timing_dag/`: `<design>_sog.pkl` (nx DiGraph), `<design>_sog_node_dict.pkl`, `<design>_sog_node_dict_init.pkl` (with delay+fanout set per node).

### 2.2 Power: toggle-rate propagation (`preproc/power/tr_propagate.py`)

- Runs **per module** (design partitioned into modules by Yosys; hierarchy listed in `design_hier.json`, e.g. bench `chipyard` → design `TinyRocket` → module list). Inputs: `example/module/<design>/<module>_sog.pkl` + `example/module/<design>_init_tr/<module>_sog_node_dict_tr.pkl` — the *initial* toggle rates are taken **from Design Compiler at the start of synthesis** (README: "The initial toggle rate is obtained from Design Compiler at the beginning of the synthesis process; the variable names from Yosys and DC are slightly different and need alignment").
- `update_node_dict`: reverse topological order; for each node without a tr, `propagate_node_tr` computes static-1 probability `t1` and toggle `tc = t1*(1-t1)` from fan-in (`g.successors`) tr values:
  - Mux/Cond (2–3 inputs, sel first): `t1 = s*a + (1-s)*b` (2-input: `t1 = s*a`)
  - And: `t1 = Π tr_i`; Or: `t1 = Π (1-tr_i)` (note: code stores this product directly, i.e. an implementation quirk — no final `1-…`); Not: `t1 = 1 - tr`; Xor: `t1 = a(1-b) + b(1-a)`; Concat/Constant: 0
  - Reg/Input/Output/Pointer/Partselect/Wire default: `t1 = tc = 0.08`; node missing from graph: `t1=0.5, tc=0.2`
- Output: `example/power_dag/<module>_sog_node_dict_propagated.pkl`.

---

## 3. Feature extraction (`feature_extract/`)

### 3.1 Area / general design vector — 14 features (`area/feature_extra_graph_stat.py` → `graph_stat.cal_oper`)

Input: `example/sog/<design>_sog.pkl` + node dict. For every node still present in the graph, using widths and `std_PPA.json`:

```
f0  seq_num      # DFF bits: Σ width over Reg nodes
f1  fanout_sum   # Σ in_degree over Reg nodes
f2  io_num       # Σ width over Input/Output/Inout
f3  and_num      # count of And operator nodes
f4  or_num
f5  not_num      # Ulnot/Unot
f6  xor_num
f7  mux_num      # Cond/Mux
f8  seq_area     = Σ area_seq[DFF]*width over Regs
f9  comb_area    = Σ area_comb[op]*width over Operator/UnaryOperator/Concat/Repeat
f10 total_area   = f8+f9
f11 stat_pwr     = Σ stat_pwr[op]*width (Regs + comb ops)
f12 dyn_pwr      = Σ dyn_pwr[op]*width
f13 total_pwr    = f11+f12
```

Output: `example/feature/<design>_sog_vec_area.json`. This vector is the **Area model input** and is also prepended to the timing and power vectors.

### 3.2 Timing (`timing/feature_extra_graph_STA.py` + `logicGraph.ProcessGraph.Graph_STA`)

Input: `example/timing_dag/*` pickles. Procedure:
1. Topological sort; `_CK_` nodes are startpoints (AT = own delay), `_Q_` nodes endpoints.
2. Propagate arrival time along the DAG keeping the **longest** path per node (`Node.update_AT`: `AT = max(AT, pred_AT + delay)`, storing the argmax path). This yields, per endpoint, a (startpoint,endpoint) pair, critical path node list, and analytical AT.
3. **Per-path feature vector (8-dim)** (`get_path_feature`): `[path_delay(analytical AT), path_len, num_mux, num_and, num_or, num_not, num_xor, 0]`.
4. A **path-level RandomForestRegressor** (`train_path_rfr.py`: `RandomForestRegressor(n_estimators=50, max_depth=30, random_state=1)`, trained on `ML_model/saved_data/feat_all_lst.pkl` / `label_lst.pkl` — per-path features vs. ground-truth path delays from DC timing reports; paper/TCAD quotes 80 estimators, depth 20) predicts each endpoint's path delay.
5. Predicted delays → slacks via `cal_timing_type(..., 'rr')`: `require_time = 1/freq − clk_unc − lib_setup = 0.5 − 0.05 − 0.032 = 0.418 ns`; `slack = require_time − (delay + input_delay)`; positive slacks clipped to 0. Full sorted slack list dumped to `pred_slack_lst/<design>_rf.json`; top-100 worst endpoint pairs kept as `wns_heap`.
6. `cal_timing`: **feat_timing = [wns, tns]** = `[min(slacks), sum(slacks)]` → `example/feature/<design>_sog_vec_timing.json`.
7. **WNS calibration** (`pred_slack_calibration.py`, research-environment script with absolute `/data/...` paths): take the first `min(0.02*seq_num, 1000)` (floor 100) predicted slacks; pick a percentile of the sorted list depending on design scale: `seq_num ≤ 3k → 10th`, `3–5k → 50th`, `> 5k → 90th` percentile → calibrated WNS; compares against DC report slacks parsed by regex `slack\s*\((\w+)\)`.

**Design-level timing model input** = 14 area features ⊕ [wns, tns] = **16 features** (see `ML_model/*/preprocess.py::load_data_timing`).

### 3.3 Power

Two scripts:
- `power/feature_extra_module_pwr.py` (per module, uses propagated tr's): 16-dim module vector
  `[pred_pwr1, pred_pwr2, fanout_sum, io_num, seq_num, comb_num, total_cell_num, io_num/total_cell_num, and_num, or_num, not_num, xor_num, mux_num, tr_io_sum, tr_sum, tr_sum/num_node]`
  where per node `pred_pwr1 = tr * min(fanout,20) * type_weight` with **power type weights: Mux/Cond 0.84, And 1, Or 1, Unot/Ulnot 0.58, Xor 0.79, Reg 1** and `pred_pwr2 = tr * fanout`. Nodes without tr default to 0.2. (These module vectors feed a module-level power model in the paper; the released script writes them to `example/feature/<design>_sog_vec_module_pwr.json`.)
- `power/feature_extra_graph_pwr.py` (design level): **power vector = 14 area features ⊕ tr_sum ⊕ tr_avr ⊕ pred_pwr = 17 features**, where `tr_sum`/`tr_avr` are read from `example/verilog/toggle_rate/<design>_tc_sum_all.json` / `_tc_avr_all.json` (DC-derived toggle-rate aggregates) and `pred_pwr` is the module-level power prediction (hard-coded `0` placeholder in the released code). Output `example/feature/<design>_sog_vec_pwr.json`.

---

## 4. Pipeline: order of execution, inputs/outputs (from README, verbatim step names)

| # | Step | Command | Input | Output |
|---|------|---------|-------|--------|
| 1 | RTL processing | `cd ys_script && yosys run_<D>_sog.ys && python3 clean_vlg.py` | `example/verilog/<D>/` (raw RTL) | `example/verilog/<D>_sog.v` |
| 2 | Verilog→graph | `cd vlg2ir && python3 auto_run.py` | `<D>_sog.v` | `example/sog/<D>_sog.pkl`, `..._node_dict.pkl` |
| 3a | Timing preproc | `cd preproc/timing && python3 delay_propagation.py` | step-2 pickles | `example/timing_dag/*` (DAG + delay-initialized node dict) |
| 3b | Power preproc | `cd preproc/power && python3 tr_propagate.py` | per-module pickles + DC initial toggle rates | `example/power_dag/*_node_dict_propagated.pkl` |
| 4a | Timing features | `python3 feature_extra_graph_STA.py` (needs trained path-level `rfr`), then `python3 pred_slack_calibration.py` | timing_dag | `example/feature/<D>_sog_vec_timing.json`, `pred_slack_lst/<D>_rf.json` |
| 4b | Power features | `python3 feature_extra_module_pwr.py` (needs DC toggle rate) then `python3 feature_extra_graph_pwr.py` | power_dag + area vec + DC tr JSONs | `<D>_sog_vec_pwr.json` |
| 4c | Area features | `python3 feature_extra_graph_stat.py` | sog pickles | `<D>_sog_vec_area.json` |
| 5 | Train | `cd ML_model/train && python3 train.py` (set `ppa_tpe` ∈ Area/TNS/WNS/Power) | feature JSONs + `example/label/<D>.json` | `ML_model/saved_model/xgboost_<tpe>_model.pkl` |
| 6 | Infer | `cd ML_model/infer && python3 infer.py` | features + saved model | printed prediction; metrics via `calculate_r_mape_rrse` (Pearson r, MAPE capped at 100%/design, RRSE) |

Label file format (`example/label/TinyRocket.json`): `{"Area": 0, "Power": 0, "WNS": 0, "TNS": 0}` (zeros in the released example — real labels come from the commercial flow).

## 5. ML models

- **Design-level (all four targets)**: `xgb.XGBRegressor(n_estimators=25, max_depth=12, nthread=20)`, one independent model per target `Area | TNS | WNS | Power` (`ML_model/train/train.py`). Feature vectors: Area = 14-d, WNS/TNS = 16-d (area ⊕ [wns_est, tns_est]), Power = 17-d.
- **Path-level (timing)**: `RandomForestRegressor(n_estimators=50, max_depth=30, random_state=1)` in the repo (`train_path_rfr.py`, with `train_test_split(random_state=1)`, default 75/25); the TCAD/paper text says 80 estimators, max depth 20. Trained on per-path 8-d features vs. ground-truth endpoint slacks/delays extracted from DC timing reports.
- **Cross-design** setting: models are trained on a set of designs and evaluated on unseen designs (paper). The released repo demonstrates only the single-design TinyRocket example; the actual 90-design training data (`saved_data/feat_all_lst.pkl`, `label_lst.pkl`) is for the path-level model. Paper compares tree models vs. Transformer/GCN and finds "lightweight tree-based models outperform the deep learning methods".

**Dataset (90 designs)** from: IWLS05 (= ISCAS89 + ITC99), OpenCores, VexRiscv (multiple configs), NVDLA, Chipyard (multiple configs, incl. TinyRocket), RISC-V cores (picorv32, mriscvcore). `pred_slack_calibration.py` enumerates the bench groups actually used: `['iscas','itc','opencores','VexRiscv','riscvcores','chipyard','NVDLA','NaxRiscv']`.

## 6. Ground-truth flow for labels

- **Synthesis:** Synopsys **Design Compiler 2021**, **NanGate 45nm** open library, `compile_ultra`; label per design = best PPA point on the Pareto curve (multiple synthesis configs run per design).
- **Metrics:** obtained via Synopsys **PrimeTime** (per-register endpoint slack, WNS, TNS, total power, total area).
- **Timing constants** in `std_PPA.json` imply a 2 GHz (0.5 ns) clock with 0.05 ns uncertainty and 0.032 ns library setup.
- **Toggle rates** for power features are dumped from DC at the beginning of synthesis (signal names must be aligned with Yosys names).
- Path-level RF labels: per-endpoint slack lines parsed out of DC `.rpt` timing reports.

## 7. Reported accuracy

- README/abstract (headline, vs. state-of-the-art on 90 designs): correlation-R improvement of **+0.33 (TNS), +0.22 (WNS), +0.15 (power)**.
- Absolute numbers (from the paper and citing papers; the arXiv PDF was not directly fetchable in this environment, so treat as approximate): **WNS R ≈ 0.86–0.87, MAPE ≈ 19–20%; TNS R ≈ 0.91–0.92, MAPE ≈ 30%**; power and area correlations are higher (area is nearly analytical, R ≈ 0.95+). Evaluation metrics used in the repo: Pearson r, MAPE (per-sample error capped at 100%), RRSE (`ML_model/infer/infer.py::calculate_r_mape_rrse`).
- Baselines in the paper: SNS (ISCA'22 deep-learning synthesis predictor), Sengupta et al. (word-level estimator), plus Transformer/GCN ablations.

---

## 8. Reproducibility with only Yosys + Python/sklearn (no commercial tools)

**Fully reproducible as-is (open-source only):**
- Step 1 SOG generation: plain Yosys (`proc; flatten; opt; fsm; opt; memory; opt; techmap; opt; write_verilog`) + attribute-stripping. (`read -verific` is a no-op / removable without Verific-enabled Yosys; plain `read_verilog` suffices for Verilog-2005 inputs.)
- Step 2 Pyverilog graph construction (Pyverilog is open-source and vendored).
- Step 3a register splitting + analytical delay initialization (constants are in the code: 0.42/0.42/0.27/0.27/0.74/1.0).
- Step 4c area features and the analytical part of timing features (`cal_oper`, graph STA, `cal_timing`) — all constants live in `std_PPA.json`.
- Steps 5–6 XGBoost/sklearn training and inference.

**Blocked on commercial tools in the original, with open substitutes:**
1. **Ground-truth labels** (DC 2021 + PrimeTime, NanGate45, compile_ultra): substitute **Yosys+ABC** (`synth; dfflibmap; abc -liberty NangateOpenCellLibrary_typical.lib`) for netlists and **OpenSTA / OpenROAD** for WNS/TNS/power/area labels. NanGate45 is freely available, so the label semantics (0.5 ns clock, 0.05 uncertainty) can be matched; absolute numbers will differ from DC but the methodology is intact.
2. **Path-level RF training labels** (per-path slacks parsed from DC reports): substitute OpenSTA `report_checks -path_group ... -group_count N` endpoint slacks on the ABC-mapped netlist.
3. **Initial toggle rates for power** (DC early-synthesis switching activity): substitute (a) the code's own defaults (0.08 for regs/IOs — the propagation code already falls back to these), or (b) RTL simulation (Verilator/Icarus + VCD → per-signal toggle rates). The released design-level power feature already hard-codes the module-level prediction to 0, so the minimal power model needs only tr_sum/tr_avr, computable from the propagated defaults.
4. **WNS calibration** compares against DC reports — optional; the percentile heuristic itself needs no tools.

**Minimal faithful reproduction (all open-source):**
1. Yosys SOG script per design → clean attributes.
2. Pyverilog → SOG graph pickles (`AST_analyzer` logic as specified in §1.2).
3. Reg/IO split → DAG; analytical fanout×weight delays; longest-path AT propagation; 8-d path features; slack via `0.418 − delay`, clip at 0 → [wns, tns] estimates.
4. 14-d area vector from `std_PPA.json` constants.
5. Toggle propagation with default 0.08 seeds → tr_sum/tr_avr → 17-d power vector.
6. Labels: Yosys+ABC on NanGate45 + OpenSTA (WNS/TNS/area/power) at a 0.5 ns clock.
7. Path-level RandomForest (50 trees, depth 30) on per-path features vs. OpenSTA endpoint slacks; design-level XGBoost (25 trees, depth 12) per target, cross-design train/test split (train on one subset of benchmark suites, test on held-out designs).

The only genuinely irreproducible artifacts are the exact DC/PrimeTime label values and DC toggle seeds; every algorithmic component (SOG, graph build, propagation, features, models) is fully specified by the open code above.
