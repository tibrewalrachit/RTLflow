#!/bin/bash
#SBATCH --job-name=rtlflow-multinode
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=8
#SBATCH --time=01:00:00
#SBATCH --output=rtlflow-%j.out
#SBATCH --error=rtlflow-%j.err
#
# RTLflow: Multi-node multi-GPU SLURM launch script
#
# Usage:
#   sbatch launch_multinode.slurm
#
# Customize:
#   --nodes           Number of nodes
#   --gpus-per-node   GPUs per node (8 for DGX A100/H100)
#   TOTAL_STIMULI     Total stimuli across all nodes
#   GPUS_PER_NODE     Must match --gpus-per-node
#   SIM_EXECUTABLE    Path to simulation binary
#
set -euo pipefail

# ---- Configuration ----
TOTAL_STIMULI=${TOTAL_STIMULI:-1000000}
GPUS_PER_NODE=${GPUS_PER_NODE:-8}
SIM_EXECUTABLE=${SIM_EXECUTABLE:-./obj_dir/sim_main}

# ---- Environment ----
module load cuda/12.x 2>/dev/null || true
module load openmpi/4.x 2>/dev/null || true

echo "RTLflow Multi-Node Launch"
echo "========================="
echo "Nodes:           $SLURM_JOB_NUM_NODES"
echo "GPUs per node:   $GPUS_PER_NODE"
echo "Total stimuli:   $TOTAL_STIMULI"
echo "Executable:      $SIM_EXECUTABLE"
echo ""

# ---- Launch with MPI ----
# Each MPI rank gets one node, manages its local GPUs
srun --mpi=pmix \
     "$SIM_EXECUTABLE" \
     --gpu-threads="$TOTAL_STIMULI" \
     --num-gpus="$GPUS_PER_NODE"
