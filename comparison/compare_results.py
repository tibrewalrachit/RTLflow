#!/usr/bin/env python3
"""
Compare performance results across GPU/accelerator-based RTL simulators:
  - RTLflow (ICPP 2022) - GPU (CUDA) batch-stimulus simulation
  - GEM (DAC 2025) - GPU (CUDA) emulator-inspired simulation
  - Parendi (ASPLOS 2025) - Graphcore IPU massively-parallel simulation

Data sourced from published papers:
  [1] RTLflow: "From RTL to CUDA: A GPU Acceleration Flow for RTL Simulation
       with Batch Stimulus" (ICPP 2022)
  [2] GEM: "GPU-Accelerated Emulator-Inspired RTL Simulation" (DAC 2025)
  [3] Parendi: "Thousand-Way Parallel RTL Simulation" (ASPLOS 2025)
"""

import json
import os

# ---------------------------------------------------------------------------
# Raw data from papers
# ---------------------------------------------------------------------------

rtlflow_data = {
    "tool": "RTLflow",
    "venue": "ICPP 2022",
    "hardware": "NVIDIA A6000 GPU",
    "approach": "Transpiles RTL to CUDA kernels; batch-stimulus parallelism",
    "designs": ["NVDLA", "Spinal", "riscv-mini"],
    "baseline": "Verilator (80-thread CPU)",
    "results": {
        "NVDLA": {
            "speedup_vs_verilator_mt": 40.7,
            "speedup_vs_verilator_st": 523.0,
            "note": "65536 stimuli, 10K cycles, vs 80-thread Verilator",
        },
        "Spinal": {
            "speedup_vs_verilator_mt": 46.7,
            "speedup_vs_verilator_st": None,
            "note": "65536 stimuli, 500K cycles, vs 80-thread Verilator",
        },
        "riscv-mini": {
            "speedup_vs_verilator_mt": None,
            "speedup_vs_verilator_st": None,
            "note": "Evaluated in paper; exact peak not reported in abstract",
        },
    },
    "key_metrics": {
        "peak_speedup_vs_mt_verilator": 46.7,
        "peak_speedup_vs_st_verilator": 523.0,
        "requires_batch_stimuli": True,
        "min_stimuli_for_speedup": "~1000+",
    },
}

gem_data = {
    "tool": "GEM",
    "venue": "DAC 2025",
    "hardware": "NVIDIA A100 GPU",
    "approach": "Emulator-inspired virtual VLIW architecture mapped to CUDA",
    "designs": ["NVDLA", "RocketChip", "Gemmini", "OpenPiton-derived multi-core"],
    "baseline": "Verilator (1-thread & 8-thread), commercial tool",
    "results": {
        "average": {
            "speedup_vs_verilator_st": 24.87,
            "speedup_vs_verilator_8t": 5.98,
            "speedup_vs_commercial": 9.15,
        },
        "NVDLA (peak)": {
            "speedup_vs_verilator_st": 64.76,
            "speedup_vs_commercial": 38.85,
        },
    },
    "key_metrics": {
        "avg_speedup_vs_st_verilator": 24.87,
        "avg_speedup_vs_8t_verilator": 5.98,
        "avg_speedup_vs_commercial": 9.15,
        "peak_speedup_vs_st_verilator": 64.76,
        "requires_batch_stimuli": False,
    },
}

parendi_data = {
    "tool": "Parendi",
    "venue": "ASPLOS 2025",
    "hardware": "Graphcore IPU-POD4 (up to 5888 cores, 4 IPU sockets)",
    "approach": "Distributes RTL across IPU tiles with fiber-based parallelism",
    "designs": ["vta", "mc", "sr2-sr15", "lr2-lr10", "pico", "bitcoin", "rocket"],
    "baseline": "Verilator on Intel Xeon 6348 (ix3) & AMD EPYC 9554 (ae4)",
    "results": {
        "geomean": {
            "speedup_vs_ix3": 2.81,
            "speedup_vs_ae4": 2.75,
        },
        "vta": {
            "parendi_khz": 454.10,
            "verilator_ix3_khz": 113.75,
            "verilator_ae4_khz": 164.73,
            "tiles": 1472,
        },
        "mc": {
            "parendi_khz": 592.83,
            "verilator_ix3_khz": 88.96,
            "verilator_ae4_khz": 143.88,
            "tiles": 1472,
        },
        "sr15": {
            "parendi_khz": 31.69,
            "verilator_ix3_khz": 9.22,
            "verilator_ae4_khz": 6.51,
            "tiles": 5888,
            "speedup_vs_ix3": 4.09,
        },
        "lr10": {
            "parendi_khz": 38.24,
            "verilator_ix3_khz": 9.27,
            "verilator_ae4_khz": 6.27,
            "tiles": 5888,
            "speedup_vs_ix3": 4.13,
            "speedup_vs_ae4": 5.02,
        },
    },
    "key_metrics": {
        "geomean_speedup_vs_ix3": 2.81,
        "geomean_speedup_vs_ae4": 2.75,
        "peak_speedup_vs_ae4": 5.02,
        "requires_batch_stimuli": False,
    },
    "cost_analysis": {
        "lr10_1B_cycles_ipu_hours": 7.26,
        "lr10_1B_cycles_ipu_cost_usd": 17,
        "lr10_1B_cycles_ae4_hours": 44.30,
        "lr10_1B_cycles_ae4_cost_usd": 69,
    },
}


def print_separator(char="=", width=80):
    print(char * width)


def print_header(title):
    print()
    print_separator()
    print(f"  {title}")
    print_separator()
    print()


def compare_tools():
    """Print a comprehensive comparison of the three tools."""

    print_header("RTL Simulation Accelerator Comparison: RTLflow vs GEM vs Parendi")

    # ---- Overview Table ----
    print("1. OVERVIEW")
    print("-" * 80)
    fmt = "{:<18} {:<22} {:<22} {:<22}"
    print(fmt.format("", "RTLflow", "GEM", "Parendi"))
    print("-" * 80)
    print(fmt.format("Venue", "ICPP 2022", "DAC 2025", "ASPLOS 2025"))
    print(fmt.format("Hardware", "NVIDIA A6000 GPU", "NVIDIA A100 GPU", "Graphcore IPU-POD4"))
    print(fmt.format("Accelerator", "GPU (CUDA)", "GPU (CUDA)", "IPU (Graphcore)"))
    print(fmt.format("Batch Stimuli?", "Yes (required)", "No", "No"))
    print(fmt.format("Open Source?", "Yes (MIT)", "Yes", "Yes"))
    print()

    # ---- Approach ----
    print("2. APPROACH")
    print("-" * 80)
    approaches = [
        ("RTLflow", "Transpiles RTL (via Verilator) into CUDA kernels that each simulate\n"
                     "                  a partition of the design across multiple stimuli in parallel.\n"
                     "                  Uses CUDA Graphs for efficient runtime scheduling."),
        ("GEM",     "Emulator-inspired: synthesizes RTL into AIG, then maps gate-level\n"
                     "                  netlist to a virtual VLIW manycore Boolean processor that\n"
                     "                  executes efficiently on CUDA GPUs."),
        ("Parendi", "Distributes RTL simulation across thousands of IPU tiles using\n"
                     "                  fiber-based parallelism. Partitions DAGs into independent\n"
                     "                  fibers to reduce inter-core communication."),
    ]
    for name, desc in approaches:
        print(f"  {name:<16}: {desc}")
        print()

    # ---- Speedup Comparison ----
    print("3. SPEEDUP vs VERILATOR")
    print("-" * 80)
    fmt = "{:<30} {:<18} {:<18} {:<18}"
    print(fmt.format("Metric", "RTLflow", "GEM", "Parendi"))
    print("-" * 80)
    print(fmt.format(
        "vs 1-thread Verilator",
        "523x (peak)",
        "24.87x (avg)",
        "N/A*",
    ))
    print(fmt.format(
        "",
        "",
        "64.76x (peak)",
        "",
    ))
    print(fmt.format(
        "vs multi-thread Verilator",
        "40-47x (peak)",
        "5.98x (avg, 8T)",
        "2.75-2.81x (geo)",
    ))
    print(fmt.format(
        "",
        "vs 80T Verilator",
        "vs 8T Verilator",
        "vs 28-64T Verilator",
    ))
    print(fmt.format(
        "vs commercial tool",
        "N/A",
        "9.15x (avg)",
        "N/A",
    ))
    print(fmt.format(
        "",
        "",
        "38.85x (peak)",
        "",
    ))
    print()
    print("  * Parendi compares against fully multi-threaded Verilator (up to 28-64 threads)")
    print("    on server-class CPUs (Intel Xeon 6348, AMD EPYC 9554).")
    print()

    # ---- NVDLA Common Benchmark ----
    print("4. NVDLA BENCHMARK (Common Design)")
    print("-" * 80)
    print("  NVDLA (NVIDIA Deep Learning Accelerator) is evaluated by both RTLflow and GEM.")
    print()
    fmt = "{:<30} {:<25} {:<25}"
    print(fmt.format("", "RTLflow", "GEM"))
    print("-" * 80)
    print(fmt.format("vs 1T Verilator", "523x", "64.76x"))
    print(fmt.format("vs MT Verilator", "40.7x (vs 80T)", "~10x (vs 8T, estimated)"))
    print(fmt.format("vs commercial", "N/A", "38.85x"))
    print(fmt.format("Stimuli required", "65536", "1 (single stimulus)"))
    print(fmt.format("Simulation cycles", "10K", "Not specified"))
    print()
    print("  NOTE: RTLflow's 523x speedup requires 65536 parallel stimuli. With a single")
    print("  stimulus, RTLflow is slower than Verilator. GEM achieves its speedups with")
    print("  a single stimulus, making it more broadly applicable.")
    print()

    # ---- Parendi Detailed Results ----
    print("5. PARENDI DETAILED RESULTS (kHz Simulation Rate)")
    print("-" * 80)
    fmt = "{:<12} {:<15} {:<15} {:<15} {:<10}"
    print(fmt.format("Design", "Parendi", "Verilator-ix3", "Verilator-ae4", "Tiles"))
    print("-" * 80)
    for design in ["vta", "mc", "sr15", "lr10"]:
        d = parendi_data["results"][design]
        print(fmt.format(
            design,
            f"{d['parendi_khz']:.2f} kHz",
            f"{d['verilator_ix3_khz']:.2f} kHz",
            f"{d['verilator_ae4_khz']:.2f} kHz",
            str(d["tiles"]),
        ))
    print()
    print(f"  Geometric mean speedup: {parendi_data['results']['geomean']['speedup_vs_ix3']}x "
          f"(vs ix3), {parendi_data['results']['geomean']['speedup_vs_ae4']}x (vs ae4)")
    print()

    # ---- Key Trade-offs ----
    print("6. KEY TRADE-OFFS")
    print("-" * 80)
    tradeoffs = [
        ("RTLflow",
         "Strengths: Massive speedup with many stimuli; built on mature Verilator infra.\n"
         "                  Weaknesses: Requires thousands of stimuli to be effective; high memory\n"
         "                  consumption; slower than Verilator with single stimulus."),
        ("GEM",
         "Strengths: Works with single stimulus; high speedup on large designs; no batch\n"
         "                  requirement; emulator-inspired approach handles SIMT heterogeneity.\n"
         "                  Weaknesses: Longer synthesis/mapping phase (one-time cost); only\n"
         "                  supports non-interactive testbenches; no async logic (latches)."),
        ("Parendi",
         "Strengths: Most cost-effective for very large multi-core designs; resilient\n"
         "                  scaling; lower compilation memory (55 GiB vs 1043 GiB for Verilator).\n"
         "                  Weaknesses: Requires specialized IPU hardware (Graphcore); more modest\n"
         "                  speedups (2-5x) compared to GPU approaches."),
    ]
    for name, desc in tradeoffs:
        print(f"  {name:<16}: {desc}")
        print()

    # ---- Summary ----
    print("7. SUMMARY")
    print("-" * 80)
    print("""
  RTLflow excels in verification workloads where thousands of test stimuli must be
  run (e.g., regression testing, fuzzing). Its batch-parallel approach achieves the
  highest raw throughput (up to 523x vs single-thread Verilator) but requires many
  stimuli to amortize GPU overhead.

  GEM provides the best single-stimulus GPU acceleration (up to 64.76x vs 1T
  Verilator). Its emulator-inspired approach elegantly solves the SIMT heterogeneity
  problem that limited prior GPU simulators. It is the most practical GPU solution
  for general RTL simulation workloads.

  Parendi targets a different niche: extremely large SoC designs (hundreds of cores)
  on Graphcore IPU hardware. While its speedups are more modest (2-5x), it offers
  superior cost-effectiveness for long-running simulations of large designs and
  requires significantly less compilation memory than Verilator.

  The three tools are largely complementary rather than competing:
    - Many stimuli, moderate designs -> RTLflow
    - Single stimulus, GPU available  -> GEM
    - Very large SoCs, long runs      -> Parendi
""")


def export_json():
    """Export comparison data as JSON for further analysis."""
    data = {
        "rtlflow": rtlflow_data,
        "gem": gem_data,
        "parendi": parendi_data,
    }
    output_path = os.path.join(os.path.dirname(__file__), "comparison_data.json")
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  Data exported to {output_path}")


if __name__ == "__main__":
    compare_tools()
    print_separator()
    print("Exporting raw data to JSON...")
    export_json()
    print("Done.")
