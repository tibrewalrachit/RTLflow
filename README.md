# RTLflow <img align="right" src="./logo.png" />

A GPU acceleration flow for RTL simulation with batch stimulus — now with **WAVETOP**, a backend targeting the Cerebras Wafer-Scale Engine (WSE).

## What is RTLflow?

RTLflow is a GPU acceleration flow for RTL simulation with batch stimulus. RTLflow first transpiles RTL into CUDA kernels that each simulate a partition of the RTL simultaneously across multiple stimulus. It also leverages CUDA Graph for efficient runtime execution. We build RTLflow atop Verilator to inherit its existing optimization facilities, such as variable reduction and partitioning algorithms, that have been rigorously tested for over 25 years in the Verilator community.

## WAVETOP: Cerebras WSE Backend

WAVETOP is a new backend that compiles RTL designs to run on the **Cerebras Wafer-Scale Engine (WSE-3)** using **Spatial Pipeline Simulation (SPS)**. SPS keeps `N_pipe` RTL clock cycles simultaneously in-flight across the WSE mesh. While cycle K's logic executes on a PE, cycle K-1's output wavelets travel independently through the fabric, hiding communication latency entirely in steady state.

### Architecture

The WAVETOP backend runs as a post-optimization pass inside Verilator. After the standard Verilator frontend (parsing, elaboration, optimization) completes, the `--wse` flag diverts the flow away from C++ emission and into six new passes:

```
Verilog RTL
    |
    v
[ Verilator Frontend ]  — parse, elaborate, optimize (unchanged)
    |
    v
[ V3WseAnalyze ]        — walk AST, build node/edge dependency graph
    |                      count expressions, state bytes, critical depth
    v
[ V3WsePartition ]      — map nodes to PE mesh coordinates
    |                      Phase A: spectral embedding (Fiedler eigenvectors)
    |                      Phase B: memory budget enforcement (44 KB/PE)
    |                      Phase C: load balancing (CoV < 0.3 target)
    v
[ V3WseColorAlloc ]     — assign wavelet colors to inter-PE signals
    |                      greedy graph coloring, narrow signal packing
    v
[ V3WseSpsSchedule ]    — compute pipeline depth N_pipe
    |                      N_pipe = min(SRAM, colors, microthreads, causality)
    v
[ V3WseEmitCsl ]        — emit CSL kernel files, layout.csl, wse_report.json
    |
    v
[ V3WseEmitHost ]       — emit runner.py host control loop
    |
    v
  obj_dir/<design>_wse/
    ├── layout.csl           — top-level PE assignment and routing
    ├── kernel_<id>.csl      — one per unique kernel class
    ├── runner.py            — host harness for fabric simulation
    ├── testbench_data.py    — pre-computed stimulus
    └── wse_report.json      — partition and performance statistics
```

### Key Design Decisions

- **Spectral partitioning** uses the graph Laplacian's Fiedler eigenvectors to place connected nodes near each other on the 2D PE mesh, minimizing inter-PE communication distance.
- **Kernel deduplication** hashes each PE's node list so PEs with identical logic share one CSL file — reducing output from ~40K files to ~5–20 for large designs.
- **Pipeline slot tagging** encodes the slot index in each wavelet (`[31:16]` = slot, `[15:0]` = data), allowing N_pipe independent cycles to share the same physical color without interference.
- **Three reserved colors** (clock=20, ctrl=19, display=18) handle broadcast clock, `$finish` signaling, and `$display` drain respectively.

### WSE Hardware Constants

| Parameter | Value |
|-----------|-------|
| Usable PEs | 750 x 994 (WSE-3) |
| Memory per PE | 48 KB total, 44 KB usable |
| Hardware colors | 24 total, 20 usable |
| Microthreads | 9 (WSE-3) |
| Clock frequency | 875 MHz |

## Build

```bash
cd RTLflow
autoconf
./configure
make -j8
```

### Prerequisites

- GNU C++ Compiler (g++ >= 5.0 with -std=c++17)
- `flex` and `bison`
- `libfl-dev`

For the GPU backend (optional):
- NVIDIA CUDA Toolkit (nvcc >= 11.0 with -std=c++17)

For the WSE backend (optional):
- Cerebras SDK (`CEREBRAS_SDK_ROOT` environment variable)
- `cslc` compiler: `$CEREBRAS_SDK_ROOT/bin/cslc`
- Minimum SDK version: 1.3 (WSE-2), 1.4 recommended (WSE-3)

```bash
sudo apt install libfl-dev flex bison
export VERILATOR_ROOT=~/RTLflow
```

## Usage

### Standard GPU Flow

```bash
rtlflow --cc design.v        # Standard C++ output
rtlflow design.v             # GPU-accelerated CUDA output (default)
```

### WAVETOP WSE Flow

```bash
rtlflow --wse design.v                        # Basic WSE compilation
rtlflow --wse --wse-arch wse3 design.v        # Target WSE-3 (default)
rtlflow --wse --wse-pes 1000 design.v         # Limit to 1000 PEs
rtlflow --wse --wse-npipe 4 design.v          # Force pipeline depth to 4
rtlflow --wse --wse-width 50 --wse-height 20 design.v  # Explicit mesh dims
```

### WSE Command-Line Options

| Flag | Default | Description |
|------|---------|-------------|
| `--wse` | off | Enable WSE backend |
| `--wse-arch <wse2\|wse3>` | `wse3` | Target architecture |
| `--wse-pes N` | 0 (auto) | Maximum PEs to use |
| `--wse-npipe N` | 0 (auto) | Force pipeline depth |
| `--wse-width W` | 0 (auto) | Mesh rectangle width |
| `--wse-height H` | 0 (auto) | Mesh rectangle height |
| `--wse-report` | on | Emit `wse_report.json` |

### Running on the WSE Fabric

After compilation, the generated `runner.py` controls the simulation:

```bash
cd obj_dir/Vdesign_wse/

# Compile CSL to fabric binary
cslc layout.csl --fabric-dims=50,20 -o out

# Run on simulator or hardware
python3 runner.py --cmaddr=<address> --cycles=10000
```

### Interpreting wse_report.json

The report contains four sections:

- **stats** — design analysis (nodes, edges, state bytes, critical depth)
- **partition** — mesh dimensions, PE utilization, hop distance, locality ratio
- **sps** — pipeline depth `N_pipe`, which bound is limiting, throughput estimate
- **colors** — color utilization, signal packing statistics

Example:
```json
{
  "sps": {
    "N_pipe": 4,
    "bindingConstraint": "microthreads",
    "estThroughputKHz": 350000.0,
    "estSpeedupVsVlt": 3500.0
  }
}
```

## Source Organization

### WAVETOP Files

| File | Purpose |
|------|---------|
| `src/wse/WseTypes.h` | Shared structs and WSE hardware constants |
| `src/V3WseAnalyze.h/cpp` | AST analysis — build dependency graph |
| `src/V3WsePartition.h/cpp` | Spectral embedding + memory + load balance |
| `src/V3WseColorAlloc.h/cpp` | Greedy wavelet color assignment |
| `src/V3WseSpsSchedule.h/cpp` | Pipeline depth computation |
| `src/V3WseEmitCsl.h/cpp` | CSL kernel and layout emission |
| `src/V3WseEmitHost.h/cpp` | Host runner.py emission |

### Test Suite

Nine test designs in `test_regress/t/` validate the backend end-to-end:

| Test | Design | Validates |
|------|--------|-----------|
| `t_wse_counter` | 32-bit counter with reset | Basic FF state, clock, reset |
| `t_wse_fifo` | 8-deep FIFO | Array state, read/write enables |
| `t_wse_alu` | 32-bit ALU | Combinational logic emission |
| `t_wse_fsm` | 8-state Moore FSM | Case statements, state encoding |
| `t_wse_pipeline` | 4-stage pipeline | Pipeline registers, forwarding |
| `t_wse_multimod` | 3 modules with handshake | Cross-PE signals, color alloc |
| `t_wse_memory` | 256x32 synchronous RAM | Banked memory model |
| `t_wse_wide` | 64-bit signals | Multi-wavelet signals |
| `t_wse_display` | `$display` usage | Display buffering, drain |

Run the differential test harness:
```bash
python3 test_regress/t/t_wse_diff.py --design test_regress/t/t_wse_counter.v
```

## Known Limitations (v0.1)

- DPI imports silently ignored (info message emitted)
- C++ testbenches not supported (Verilog-only)
- `$dumpvars` / VCD tracing not supported
- Combinational loops cause a fatal error (no unrolling)
- Multi-clock designs: all clocks treated as synchronous
- FP64: WSE supports FP32/FP16 only — `real`/`shortreal` types unsupported
- `--wse-arch wse3` exists but WSE-2 semantics implemented first

## Examples

Please go to [RTLflow benchmarks](https://github.com/dian-lun-lin/RTLflow-benchmarks) for GPU backend examples.

## License

RTLflow is licensed with the MIT License.


