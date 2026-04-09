#!/bin/bash
#SBATCH --job-name=rtlflow-nvl72
#SBATCH --nodes=1
#SBATCH --gpus=72
#SBATCH --time=01:00:00
#SBATCH --output=rtlflow-nvl72-%j.out
#SBATCH --error=rtlflow-nvl72-%j.err
#
# RTLflow: NVIDIA GB200 NVL72 launch script
#
# The GB200 NVL72 presents 72 Blackwell GPUs as a single node via NVSwitch.
# Each GPU has 192GB HBM3e. Total: 13.8TB GPU memory.
# NVLink bandwidth: 1.8 TB/s bidirectional per GPU.
#
# RTLflow stimuli are embarrassingly parallel, so all 72 GPUs can be
# utilized with zero inter-GPU communication during simulation.
#
# Usage:
#   sbatch launch_nvl72.slurm
#
# For very large designs, configure TOTAL_STIMULI accordingly.
# With 72 GPUs x 192GB, you can simulate tens of millions of stimuli
# even for complex RTL designs.
#
set -euo pipefail

# ---- Configuration ----
TOTAL_STIMULI=${TOTAL_STIMULI:-10000000}
NUM_GPUS=72
SIM_EXECUTABLE=${SIM_EXECUTABLE:-./obj_dir/sim_main}

# ---- Environment ----
module load cuda/12.x 2>/dev/null || true

echo "RTLflow GB200 NVL72 Launch"
echo "=========================="
echo "GPUs:            $NUM_GPUS (GB200 NVL72)"
echo "Total stimuli:   $TOTAL_STIMULI"
echo "Stimuli per GPU: $((TOTAL_STIMULI / NUM_GPUS))"
echo "Executable:      $SIM_EXECUTABLE"
echo ""

# NVL72 is single-node, no MPI needed
exec "$SIM_EXECUTABLE" \
     --gpu-threads="$TOTAL_STIMULI" \
     --num-gpus="$NUM_GPUS"
