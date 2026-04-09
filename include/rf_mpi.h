#pragma once

#ifdef RTLFLOW_MPI
#include <mpi.h>
#endif

#include <cstddef>
#include <cstring>
#include <algorithm>

// begin of namespace RF =========================================================================
namespace RF {

// Thin MPI wrapper for multi-node RTLflow stimulus distribution.
// When RTLFLOW_MPI is not defined, all operations are no-ops (single-node mode).
//
// Usage in user testbench:
//   #ifdef RTLFLOW_MPI
//   MPI_Init(&argc, &argv);
//   #endif
//   RF::RTLflowMPI mpi(total_stimuli);
//   RF::RTLflow rtlflow(mpi.local_threads);  // auto-detect local GPUs
//   // ... run simulation ...
//   #ifdef RTLFLOW_MPI
//   MPI_Finalize();
//   #endif
//
struct RTLflowMPI {
    int rank{0};
    int world_size{1};
    size_t global_threads;
    size_t local_threads;
    size_t global_offset;

    explicit RTLflowMPI(size_t total_threads)
        : global_threads{total_threads} {
#ifdef RTLFLOW_MPI
        MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        MPI_Comm_size(MPI_COMM_WORLD, &world_size);
#endif
        size_t per_node = global_threads / static_cast<size_t>(world_size);
        size_t remainder = global_threads % static_cast<size_t>(world_size);
        local_threads = per_node + (static_cast<size_t>(rank) < remainder ? 1 : 0);
        global_offset = static_cast<size_t>(rank) * per_node
                        + std::min(static_cast<size_t>(rank), remainder);
    }

    // Synchronize all nodes
    void barrier() {
#ifdef RTLFLOW_MPI
        MPI_Barrier(MPI_COMM_WORLD);
#endif
    }

    // Gather per-node results to root (rank 0)
    // local_buf: this node's results
    // local_count: number of elements of type T
    // global_buf: output buffer (only meaningful on root)
    // root: root rank (default 0)
    template <typename T>
    void gather(const T* local_buf, size_t local_count,
                T* global_buf, int root = 0) {
#ifdef RTLFLOW_MPI
        MPI_Gather(local_buf, static_cast<int>(local_count * sizeof(T)), MPI_BYTE,
                   global_buf, static_cast<int>(local_count * sizeof(T)), MPI_BYTE,
                   root, MPI_COMM_WORLD);
#else
        std::memcpy(global_buf, local_buf, local_count * sizeof(T));
#endif
    }

    // Variable-length gather for uneven partitions
    template <typename T>
    void gatherv(const T* local_buf, size_t local_count,
                 T* global_buf, const int* recvcounts, const int* displs,
                 int root = 0) {
#ifdef RTLFLOW_MPI
        MPI_Gatherv(local_buf, static_cast<int>(local_count * sizeof(T)), MPI_BYTE,
                    global_buf, recvcounts, displs, MPI_BYTE,
                    root, MPI_COMM_WORLD);
#else
        std::memcpy(global_buf, local_buf, local_count * sizeof(T));
#endif
    }

    bool is_root() const { return rank == 0; }
};

}  // namespace RF
