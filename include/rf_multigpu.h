#pragma once

#include <vector>
#include <algorithm>
#include <cuda_runtime.h>

// begin of namespace RF =========================================================================
namespace RF {

// Forward declarations from rf_heavy.h
using CData = unsigned char;
using SData = unsigned short int;
using IData = uint32_t;
using QData = unsigned long;

// Per-GPU device state -- each GPU owns a partition of stimuli
struct DeviceState {
    int device_id{0};
    size_t local_threads{0};    // number of stimuli assigned to this GPU
    size_t global_offset{0};    // offset into global stimulus index space

    // Per-device signal arrays (device memory)
    CData* _csignals{nullptr};
    SData* _ssignals{nullptr};
    IData* _isignals{nullptr};
    QData* _qsignals{nullptr};

    // Per-device convergence tracking
    IData* change{nullptr};
    bool*  done{nullptr};
};

// Helper: find which device owns a given global stimulus index
// Returns device index into the devices vector
inline size_t find_device(const std::vector<DeviceState>& devs, size_t global_idx) {
    for (size_t d = 0; d < devs.size(); ++d) {
        if (global_idx >= devs[d].global_offset &&
            global_idx < devs[d].global_offset + devs[d].local_threads) {
            return d;
        }
    }
    return 0;  // fallback to device 0
}

// Helper: partition N stimuli evenly across num_gpus GPUs
// Returns vector of (local_threads, global_offset) pairs
inline std::vector<std::pair<size_t, size_t>> partition_stimuli(
        size_t total_threads, size_t num_gpus) {
    std::vector<std::pair<size_t, size_t>> partitions(num_gpus);
    size_t per_gpu = total_threads / num_gpus;
    size_t remainder = total_threads % num_gpus;
    size_t offset = 0;
    for (size_t d = 0; d < num_gpus; ++d) {
        size_t local = per_gpu + (d < remainder ? 1 : 0);
        partitions[d] = {local, offset};
        offset += local;
    }
    return partitions;
}

}  // namespace RF
