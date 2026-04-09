#!/bin/bash
# RTLflow: Single-node multi-GPU launch helper
#
# Usage: ./launch_multigpu.sh <executable> <total_stimuli> [num_gpus]
#
# Examples:
#   ./launch_multigpu.sh ./obj_dir/sim_main 100000          # auto-detect GPUs
#   ./launch_multigpu.sh ./obj_dir/sim_main 100000 4        # use 4 GPUs
#   ./launch_multigpu.sh ./obj_dir/sim_main 1000000 8       # use 8 GPUs (DGX)
#
set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 <executable> <total_stimuli> [num_gpus]"
    echo ""
    echo "Arguments:"
    echo "  executable      Path to the RTLflow simulation binary"
    echo "  total_stimuli   Total number of test stimuli to simulate"
    echo "  num_gpus        Number of GPUs to use (default: auto-detect)"
    exit 1
fi

EXECUTABLE="$1"
TOTAL_STIMULI="$2"

if [ $# -ge 3 ]; then
    NUM_GPUS="$3"
else
    NUM_GPUS=$(nvidia-smi -L 2>/dev/null | wc -l)
    if [ "$NUM_GPUS" -eq 0 ]; then
        echo "Error: No GPUs detected. Ensure nvidia-smi is available."
        exit 1
    fi
fi

echo "RTLflow Multi-GPU Launch"
echo "========================"
echo "Executable:      $EXECUTABLE"
echo "Total stimuli:   $TOTAL_STIMULI"
echo "Number of GPUs:  $NUM_GPUS"
echo ""

# Set visible devices
export CUDA_VISIBLE_DEVICES=$(seq -s, 0 $((NUM_GPUS-1)))
echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"

# Launch
exec "$EXECUTABLE" --gpu-threads="$TOTAL_STIMULI" --num-gpus="$NUM_GPUS"
