# RTL Simulation Accelerator Comparison: RTLflow vs GEM vs Parendi

Comparison of three accelerator-based RTL simulation tools, based on published results.

## Tools

| | RTLflow | GEM | Parendi |
|---|---|---|---|
| **Venue** | ICPP 2022 | DAC 2025 | ASPLOS 2025 |
| **Hardware** | NVIDIA A6000 GPU | NVIDIA A100 GPU | Graphcore IPU-POD4 |
| **Accelerator** | GPU (CUDA) | GPU (CUDA) | IPU (Graphcore) |
| **Batch Stimuli Required?** | Yes | No | No |
| **Open Source** | Yes (MIT) | Yes | Yes |

## Approach

- **RTLflow**: Transpiles RTL (via Verilator) into CUDA kernels that each simulate a partition of the design across multiple stimuli in parallel. Uses CUDA Graphs for efficient runtime scheduling.
- **GEM**: Emulator-inspired: synthesizes RTL into AIG, then maps the gate-level netlist to a virtual VLIW manycore Boolean processor that executes efficiently on CUDA GPUs.
- **Parendi**: Distributes RTL simulation across thousands of IPU tiles using fiber-based parallelism. Partitions DAGs into independent fibers to reduce inter-core communication.

## Speedup vs Verilator

| Metric | RTLflow | GEM | Parendi |
|---|---|---|---|
| vs 1-thread Verilator | **523x** (peak, 65536 stimuli) | **24.87x** (avg) / **64.76x** (peak) | N/A* |
| vs multi-thread Verilator | **40-47x** (peak, vs 80T) | **5.98x** (avg, vs 8T) | **2.75-2.81x** (geomean, vs 28-64T) |
| vs commercial tool | N/A | **9.15x** (avg) / **38.85x** (peak) | N/A |

\* Parendi compares against fully multi-threaded Verilator (28-64 threads) on server-class CPUs.

## NVDLA Benchmark (Common Design)

NVDLA is evaluated by both RTLflow and GEM:

| | RTLflow | GEM |
|---|---|---|
| vs 1T Verilator | 523x | 64.76x |
| vs MT Verilator | 40.7x (vs 80T) | ~10x (vs 8T, estimated) |
| vs commercial tool | N/A | 38.85x |
| Stimuli required | 65,536 | 1 (single stimulus) |

> **Note**: RTLflow's 523x speedup requires 65,536 parallel stimuli. With a single stimulus, RTLflow is slower than Verilator. GEM achieves its speedups with a single stimulus.

## Parendi Detailed Results

| Design | Parendi (kHz) | Verilator-ix3 (kHz) | Verilator-ae4 (kHz) | IPU Tiles |
|---|---|---|---|---|
| vta | 454.10 | 113.75 | 164.73 | 1,472 |
| mc | 592.83 | 88.96 | 143.88 | 1,472 |
| sr15 | 31.69 | 9.22 | 6.51 | 5,888 |
| lr10 | 38.24 | 9.27 | 6.27 | 5,888 |

Geometric mean speedup: **2.81x** (vs Intel Xeon 6348), **2.75x** (vs AMD EPYC 9554)

### Cost Analysis (lr10, 1 billion cycles)

| Platform | Time | Estimated Cost |
|---|---|---|
| IPU-POD4 | 7.26 hours | ~$17 |
| AMD EPYC 9554 | 44.30 hours | ~$69 |

## Key Trade-offs

### RTLflow
- **Strengths**: Massive speedup with many stimuli; built on mature Verilator infrastructure
- **Weaknesses**: Requires thousands of stimuli; high memory consumption; slower than Verilator with single stimulus

### GEM
- **Strengths**: Works with single stimulus; high speedup on large designs; emulator-inspired approach handles SIMT heterogeneity
- **Weaknesses**: Longer synthesis/mapping phase (one-time cost); only non-interactive testbenches; no async logic (latches)

### Parendi
- **Strengths**: Most cost-effective for very large multi-core SoC designs; resilient scaling; lower compilation memory (55 GiB vs 1,043 GiB for Verilator)
- **Weaknesses**: Requires specialized IPU hardware (Graphcore); more modest speedups (2-5x)

## Summary

The three tools are largely **complementary** rather than competing:

| Use Case | Best Tool |
|---|---|
| Many stimuli, moderate-size designs (regression, fuzzing) | **RTLflow** |
| Single stimulus, GPU available (general simulation) | **GEM** |
| Very large SoCs, long-running simulations | **Parendi** |

## Sources

- [RTLflow paper (ICPP 2022)](https://dl.acm.org/doi/10.1145/3545008.3545091)
- [GEM paper (DAC 2025)](https://research.nvidia.com/publication/2025-06_gem-gpu-accelerated-emulator-inspired-rtl-simulation)
- [Parendi paper (ASPLOS 2025)](https://arxiv.org/abs/2403.04714)
