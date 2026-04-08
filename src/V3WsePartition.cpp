// -*- mode: C++; c-file-style: "cc-mode" -*-
//*************************************************************************
// DESCRIPTION: Verilator: WAVETOP WSE backend — design partitioning
//
// Implements three-phase partitioning:
//   Phase A: Spectral embedding (Fiedler eigenvectors)
//   Phase B: Memory budget enforcement
//   Phase C: Load balancing
//
// Code available from: https://verilator.org
//
//*************************************************************************
//
// Copyright 2024 by Wilson Snyder. This program is free software; you
// can redistribute it and/or modify it under the terms of either the GNU
// Lesser General Public License Version 3 or the Perl Artistic License
// Version 2.0.
// SPDX-License-Identifier: LGPL-3.0-only OR Artistic-2.0
//
//*************************************************************************

#include "config_build.h"
#include "verilatedos.h"

#include "V3Global.h"
#include "V3WsePartition.h"
#include "V3Error.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <random>
#include <unordered_map>
#include <unordered_set>
#include <vector>

//######################################################################
// Sparse matrix-vector multiply for Laplacian

namespace {

// Sparse row representation of the Laplacian
struct SparseRow {
    std::vector<std::pair<uint32_t, double>> entries;  // (col, weight)
    double diagonal = 0.0;
};

// Compute y = L * x where L is the graph Laplacian
void laplacianMul(const std::vector<SparseRow>& L, const std::vector<double>& x,
                  std::vector<double>& y) {
    uint32_t n = static_cast<uint32_t>(L.size());
    for (uint32_t i = 0; i < n; ++i) {
        double sum = L[i].diagonal * x[i];
        for (const auto& entry : L[i].entries) { sum -= entry.second * x[entry.first]; }
        y[i] = sum;
    }
}

// Dot product
double dot(const std::vector<double>& a, const std::vector<double>& b) {
    double s = 0.0;
    for (size_t i = 0; i < a.size(); ++i) s += a[i] * b[i];
    return s;
}

// Normalize vector, return norm
double normalize(std::vector<double>& v) {
    double norm = std::sqrt(dot(v, v));
    if (norm > 1e-15) {
        for (auto& x : v) x /= norm;
    }
    return norm;
}

// Subtract projection: v = v - (v.u)*u (assumes u is unit)
void deflate(std::vector<double>& v, const std::vector<double>& u) {
    double c = dot(v, u);
    for (size_t i = 0; i < v.size(); ++i) v[i] -= c * u[i];
}

// Power iteration to find smallest eigenvector of L (after deflating constant vector).
// Uses inverse iteration: solve (L + shift*I)^{-1} x via Jacobi iteration.
// For small/medium graphs this is efficient enough.
// Returns the eigenvector.
std::vector<double> findFiedlerVector(const std::vector<SparseRow>& L, uint32_t n,
                                      const std::vector<double>* prevEigVec = nullptr) {
    // Initialize with random vector
    std::mt19937 rng(42);
    std::uniform_real_distribution<double> dist(-1.0, 1.0);
    std::vector<double> v(n);
    for (uint32_t i = 0; i < n; ++i) v[i] = dist(rng);

    // The constant vector (1/sqrt(n), ..., 1/sqrt(n)) is the first eigenvector
    // with eigenvalue 0. Deflate it out.
    std::vector<double> ones(n, 1.0 / std::sqrt(static_cast<double>(n)));
    deflate(v, ones);
    if (prevEigVec) deflate(v, *prevEigVec);
    normalize(v);

    // Inverse power iteration using Jacobi-preconditioned method
    // We want the smallest non-zero eigenvalue, so we use inverse iteration
    // with a small shift to avoid singularity.
    std::vector<double> Lv(n);
    const int maxIter = 200;
    for (int iter = 0; iter < maxIter; ++iter) {
        // Jacobi iteration: approximate solve (L + eps*I) y = v
        // Use diagonal preconditioning: y_i = v_i / (L_ii + eps)
        const double eps = 1e-6;
        std::vector<double> y(n);
        for (uint32_t i = 0; i < n; ++i) {
            double denom = L[i].diagonal + eps;
            if (std::abs(denom) < 1e-15) denom = 1e-15;
            y[i] = v[i] / denom;
        }

        // A few Jacobi relaxation steps for better approximation
        for (int jiter = 0; jiter < 5; ++jiter) {
            std::vector<double> ynew(n);
            for (uint32_t i = 0; i < n; ++i) {
                double sum = v[i];
                for (const auto& entry : L[i].entries) { sum += entry.second * y[entry.first]; }
                double denom = L[i].diagonal + eps;
                if (std::abs(denom) < 1e-15) denom = 1e-15;
                ynew[i] = sum / denom;
            }
            y = ynew;
        }

        // Deflate out constant vector and previous eigenvector
        deflate(y, ones);
        if (prevEigVec) deflate(y, *prevEigVec);
        normalize(y);
        v = y;
    }

    return v;
}

}  // namespace

//######################################################################
// Partitioner implementation

class WsePartitioner {
    const WseDesignStats& m_stats;
    uint32_t m_meshWidth = 0;
    uint32_t m_meshHeight = 0;

    // PE grid: (x, y) -> list of node IDs
    std::unordered_map<uint64_t, std::vector<uint32_t>> m_peNodes;
    // Per-node placement
    std::vector<uint32_t> m_nodeX;
    std::vector<uint32_t> m_nodeY;

    static uint64_t peKey(uint32_t x, uint32_t y) {
        return (static_cast<uint64_t>(x) << 32) | y;
    }

    //------------------------------------------------------------------
    // Phase A: Spectral Embedding
    void phaseA_spectralEmbedding() {
        uint32_t n = m_stats.totalNodes;
        if (n == 0) return;

        UINFO(3, "WSE: Phase A — Spectral embedding for " << n << " nodes" << endl);

        // Build sparse Laplacian
        std::vector<SparseRow> L(n);
        for (const auto& edge : m_stats.edges) {
            if (edge.srcNodeId >= n || edge.dstNodeId >= n) continue;
            double w = edge.isHighFanout ? 0.0 : static_cast<double>(edge.widthBits);
            if (w <= 0.0) continue;

            L[edge.srcNodeId].entries.push_back({edge.dstNodeId, w});
            L[edge.srcNodeId].diagonal += w;
            L[edge.dstNodeId].entries.push_back({edge.srcNodeId, w});
            L[edge.dstNodeId].diagonal += w;
        }

        // For very small graphs (1-2 nodes), just place linearly
        if (n <= 2) {
            m_nodeX.resize(n);
            m_nodeY.resize(n);
            for (uint32_t i = 0; i < n; ++i) {
                m_nodeX[i] = i % m_meshWidth;
                m_nodeY[i] = i / m_meshWidth;
            }
            return;
        }

        // Find Fiedler vector (2nd smallest eigenvector)
        std::vector<double> v2 = findFiedlerVector(L, n);

        // Find 3rd eigenvector
        std::vector<double> v3 = findFiedlerVector(L, n, &v2);

        // Scale to mesh coordinates
        // Find min/max of each eigenvector
        double minV2 = *std::min_element(v2.begin(), v2.end());
        double maxV2 = *std::max_element(v2.begin(), v2.end());
        double minV3 = *std::min_element(v3.begin(), v3.end());
        double maxV3 = *std::max_element(v3.begin(), v3.end());

        double rangeV2 = maxV2 - minV2;
        double rangeV3 = maxV3 - minV3;
        if (rangeV2 < 1e-15) rangeV2 = 1.0;
        if (rangeV3 < 1e-15) rangeV3 = 1.0;

        m_nodeX.resize(n);
        m_nodeY.resize(n);
        for (uint32_t i = 0; i < n; ++i) {
            double nx = (v2[i] - minV2) / rangeV2 * (m_meshWidth - 1);
            double ny = (v3[i] - minV3) / rangeV3 * (m_meshHeight - 1);
            m_nodeX[i] = std::min(static_cast<uint32_t>(std::round(nx)), m_meshWidth - 1);
            m_nodeY[i] = std::min(static_cast<uint32_t>(std::round(ny)), m_meshHeight - 1);
        }
    }

    //------------------------------------------------------------------
    // Phase B: Memory Budget Enforcement
    void phaseB_memoryBudget() {
        UINFO(3, "WSE: Phase B — Memory budget enforcement" << endl);

        // Build PE -> nodes mapping
        m_peNodes.clear();
        for (uint32_t i = 0; i < m_stats.totalNodes; ++i) {
            m_peNodes[peKey(m_nodeX[i], m_nodeY[i])].push_back(i);
        }

        for (int iter = 0; iter < 100; ++iter) {
            bool anyOverBudget = false;

            for (auto& pe : m_peNodes) {
                uint32_t totalBytes = 0;
                for (uint32_t nid : pe.second) { totalBytes += m_stats.nodes[nid].stateBytes; }

                if (totalBytes <= WSE_MEM_BUDGET_BYTES) continue;
                anyOverBudget = true;

                // Find heaviest node
                uint32_t heaviestIdx = 0;
                uint32_t heaviestBytes = 0;
                for (size_t j = 0; j < pe.second.size(); ++j) {
                    uint32_t nid = pe.second[j];
                    if (m_stats.nodes[nid].stateBytes > heaviestBytes) {
                        heaviestBytes = m_stats.nodes[nid].stateBytes;
                        heaviestIdx = static_cast<uint32_t>(j);
                    }
                }

                uint32_t nodeToMove = pe.second[heaviestIdx];
                uint32_t cx = m_nodeX[nodeToMove];
                uint32_t cy = m_nodeY[nodeToMove];

                // Find least-loaded Manhattan-1 neighbor
                uint32_t bestX = cx, bestY = cy;
                uint32_t bestLoad = UINT32_MAX;
                int dx[] = {-1, 1, 0, 0};
                int dy[] = {0, 0, -1, 1};
                for (int d = 0; d < 4; ++d) {
                    int nx = static_cast<int>(cx) + dx[d];
                    int ny = static_cast<int>(cy) + dy[d];
                    if (nx < 0 || ny < 0 || static_cast<uint32_t>(nx) >= m_meshWidth
                        || static_cast<uint32_t>(ny) >= m_meshHeight)
                        continue;
                    uint32_t nBytes = 0;
                    auto nit = m_peNodes.find(peKey(nx, ny));
                    if (nit != m_peNodes.end()) {
                        for (uint32_t nid : nit->second) {
                            nBytes += m_stats.nodes[nid].stateBytes;
                        }
                    }
                    if (nBytes < bestLoad) {
                        bestLoad = nBytes;
                        bestX = static_cast<uint32_t>(nx);
                        bestY = static_cast<uint32_t>(ny);
                    }
                }

                if (bestX != cx || bestY != cy) {
                    // Migrate node
                    pe.second.erase(pe.second.begin() + heaviestIdx);
                    m_nodeX[nodeToMove] = bestX;
                    m_nodeY[nodeToMove] = bestY;
                    m_peNodes[peKey(bestX, bestY)].push_back(nodeToMove);
                }
            }

            if (!anyOverBudget) break;

            if (iter == 99) {
                // Final check
                for (auto& pe : m_peNodes) {
                    uint32_t totalBytes = 0;
                    for (uint32_t nid : pe.second) { totalBytes += m_stats.nodes[nid].stateBytes; }
                    if (totalBytes > WSE_MEM_BUDGET_BYTES) {
                        v3error("WSE: Cannot fit design into 44KB/PE at "
                                << m_stats.totalNodes << " PEs. Try --wse-pes <larger_N>.");
                        return;
                    }
                }
            }
        }
    }

    //------------------------------------------------------------------
    // Phase C: Load Balancing
    void phaseC_loadBalance() {
        UINFO(3, "WSE: Phase C — Load balancing" << endl);

        // Rebuild PE mapping after phase B
        m_peNodes.clear();
        for (uint32_t i = 0; i < m_stats.totalNodes; ++i) {
            m_peNodes[peKey(m_nodeX[i], m_nodeY[i])].push_back(i);
        }

        for (int sweep = 0; sweep < 50; ++sweep) {
            // Compute per-PE cycle totals
            std::unordered_map<uint64_t, uint32_t> peCycles;
            for (auto& pe : m_peNodes) {
                uint32_t total = 0;
                for (uint32_t nid : pe.second) { total += m_stats.nodes[nid].estCycles; }
                peCycles[pe.first] = total;
            }

            // Compute CoV
            if (peCycles.empty()) break;
            double sum = 0.0;
            for (auto& pc : peCycles) sum += pc.second;
            double mean = sum / peCycles.size();
            if (mean < 1e-15) break;

            double variance = 0.0;
            for (auto& pc : peCycles) {
                double diff = pc.second - mean;
                variance += diff * diff;
            }
            double stddev = std::sqrt(variance / peCycles.size());
            double cov = stddev / mean;

            UINFO(4, "WSE: Load balance sweep " << sweep << " CoV=" << cov << endl);
            if (cov <= 0.3) break;

            // Local swap pass
            bool improved = false;
            for (auto& pe : m_peNodes) {
                if (pe.second.empty()) continue;
                uint32_t px = static_cast<uint32_t>(pe.first >> 32);
                uint32_t py = static_cast<uint32_t>(pe.first & 0xFFFFFFFF);

                // Find most expensive node on this PE
                uint32_t maxCycNode = pe.second[0];
                uint32_t maxCycles = 0;
                for (uint32_t nid : pe.second) {
                    if (m_stats.nodes[nid].estCycles > maxCycles) {
                        maxCycles = m_stats.nodes[nid].estCycles;
                        maxCycNode = nid;
                    }
                }

                // Find least-loaded neighbor PE
                uint32_t bestNeighborKey = pe.first;
                uint32_t bestNeighborCycles = UINT32_MAX;
                int dx[] = {-1, 1, 0, 0};
                int dy[] = {0, 0, -1, 1};
                for (int d = 0; d < 4; ++d) {
                    int nx = static_cast<int>(px) + dx[d];
                    int ny = static_cast<int>(py) + dy[d];
                    if (nx < 0 || ny < 0 || static_cast<uint32_t>(nx) >= m_meshWidth
                        || static_cast<uint32_t>(ny) >= m_meshHeight)
                        continue;
                    uint64_t nkey = peKey(nx, ny);
                    uint32_t nc = 0;
                    auto nit = peCycles.find(nkey);
                    if (nit != peCycles.end()) nc = nit->second;
                    if (nc < bestNeighborCycles) {
                        bestNeighborCycles = nc;
                        bestNeighborKey = nkey;
                    }
                }

                if (bestNeighborKey == pe.first) continue;
                if (peCycles[pe.first] <= bestNeighborCycles) continue;

                // Try swap: move most expensive node from this PE to neighbor
                auto& neighborNodes = m_peNodes[bestNeighborKey];

                // Find cheapest node on neighbor (to swap back)
                if (!neighborNodes.empty()) {
                    uint32_t minCycNode = neighborNodes[0];
                    uint32_t minCycles = UINT32_MAX;
                    for (uint32_t nid : neighborNodes) {
                        if (m_stats.nodes[nid].estCycles < minCycles) {
                            minCycles = m_stats.nodes[nid].estCycles;
                            minCycNode = nid;
                        }
                    }

                    // Check if swap improves balance
                    uint32_t curDiff = peCycles[pe.first] > bestNeighborCycles
                                           ? peCycles[pe.first] - bestNeighborCycles
                                           : bestNeighborCycles - peCycles[pe.first];
                    uint32_t newThis = peCycles[pe.first] - maxCycles + minCycles;
                    uint32_t newNeighbor = bestNeighborCycles + maxCycles - minCycles;
                    uint32_t newDiff
                        = newThis > newNeighbor ? newThis - newNeighbor : newNeighbor - newThis;

                    if (newDiff < curDiff) {
                        // Perform swap
                        uint32_t nbx = static_cast<uint32_t>(bestNeighborKey >> 32);
                        uint32_t nby = static_cast<uint32_t>(bestNeighborKey & 0xFFFFFFFF);

                        pe.second.erase(
                            std::find(pe.second.begin(), pe.second.end(), maxCycNode));
                        neighborNodes.erase(
                            std::find(neighborNodes.begin(), neighborNodes.end(), minCycNode));

                        pe.second.push_back(minCycNode);
                        neighborNodes.push_back(maxCycNode);

                        m_nodeX[maxCycNode] = nbx;
                        m_nodeY[maxCycNode] = nby;
                        m_nodeX[minCycNode] = px;
                        m_nodeY[minCycNode] = py;

                        improved = true;
                    }
                } else {
                    // No neighbor nodes, just migrate
                    uint32_t nbx = static_cast<uint32_t>(bestNeighborKey >> 32);
                    uint32_t nby = static_cast<uint32_t>(bestNeighborKey & 0xFFFFFFFF);

                    pe.second.erase(
                        std::find(pe.second.begin(), pe.second.end(), maxCycNode));
                    neighborNodes.push_back(maxCycNode);
                    m_nodeX[maxCycNode] = nbx;
                    m_nodeY[maxCycNode] = nby;
                    improved = true;
                }
            }

            if (!improved) break;
        }
    }

    //------------------------------------------------------------------
    // Build final WsePeMap result
    WsePeMap buildResult() {
        // Rebuild PE mapping
        m_peNodes.clear();
        for (uint32_t i = 0; i < m_stats.totalNodes; ++i) {
            m_peNodes[peKey(m_nodeX[i], m_nodeY[i])].push_back(i);
        }

        WsePeMap result;
        result.meshWidth = m_meshWidth;
        result.meshHeight = m_meshHeight;

        // Build assignments
        result.assignments.resize(m_stats.totalNodes);
        for (uint32_t i = 0; i < m_stats.totalNodes; ++i) {
            result.assignments[i].nodeId = i;
            result.assignments[i].peX = m_nodeX[i];
            result.assignments[i].peY = m_nodeY[i];
        }

        // Build PE info
        for (auto& pe : m_peNodes) {
            WsePeInfo info;
            info.peX = static_cast<uint32_t>(pe.first >> 32);
            info.peY = static_cast<uint32_t>(pe.first & 0xFFFFFFFF);
            info.nodeIds = pe.second;
            info.totalStateBytes = 0;
            info.estCycles = 0;
            for (uint32_t nid : pe.second) {
                info.totalStateBytes += m_stats.nodes[nid].stateBytes;
                info.estCycles += m_stats.nodes[nid].estCycles;
            }
            result.pes.push_back(info);
        }

        // Compute avgHopDistance
        double totalHops = 0.0;
        uint32_t edgeCount = 0;
        for (const auto& edge : m_stats.edges) {
            if (edge.srcNodeId < m_stats.totalNodes && edge.dstNodeId < m_stats.totalNodes) {
                int dx = static_cast<int>(m_nodeX[edge.srcNodeId])
                         - static_cast<int>(m_nodeX[edge.dstNodeId]);
                int dy = static_cast<int>(m_nodeY[edge.srcNodeId])
                         - static_cast<int>(m_nodeY[edge.dstNodeId]);
                totalHops += std::abs(dx) + std::abs(dy);
                ++edgeCount;
            }
        }
        result.avgHopDistance = edgeCount > 0 ? totalHops / edgeCount : 0.0;

        // Compute localityAlpha (ratio vs random placement expected distance)
        // Random placement expected Manhattan distance ~= (meshW + meshH) / 3
        double randomExpected
            = (static_cast<double>(m_meshWidth) + static_cast<double>(m_meshHeight)) / 3.0;
        result.localityAlpha
            = randomExpected > 0.0 ? result.avgHopDistance / randomExpected : 1.0;

        UINFO(2, "WSE: Partition complete. Mesh="
                      << m_meshWidth << "x" << m_meshHeight << " PEs=" << result.pes.size()
                      << " AvgHops=" << result.avgHopDistance
                      << " Locality=" << result.localityAlpha << endl);

        return result;
    }

public:
    explicit WsePartitioner(const WseDesignStats& stats)
        : m_stats{stats} {}

    WsePeMap partition() {
        uint32_t n = m_stats.totalNodes;
        if (n == 0) {
            WsePeMap empty;
            empty.meshWidth = 1;
            empty.meshHeight = 1;
            empty.avgHopDistance = 0;
            empty.localityAlpha = 0;
            return empty;
        }

        // Determine mesh dimensions
        uint32_t optWidth = v3Global.opt.wseWidth();
        uint32_t optHeight = v3Global.opt.wseHeight();
        uint32_t optPes = v3Global.opt.wsePes();

        if (optWidth > 0 && optHeight > 0) {
            m_meshWidth = optWidth;
            m_meshHeight = optHeight;
        } else if (optPes > 0) {
            // Auto-size to fit optPes in a near-square rectangle
            m_meshWidth = static_cast<uint32_t>(std::ceil(std::sqrt(static_cast<double>(optPes))));
            m_meshHeight = (optPes + m_meshWidth - 1) / m_meshWidth;
        } else {
            // Auto-size: need at least totalNodes * 1.3 PEs
            uint32_t minPes = static_cast<uint32_t>(std::ceil(n * 1.3));
            m_meshWidth
                = static_cast<uint32_t>(std::ceil(std::sqrt(static_cast<double>(minPes))));
            m_meshHeight = (minPes + m_meshWidth - 1) / m_meshWidth;
        }

        // Bound by WSE usable area
        m_meshWidth = std::min(m_meshWidth, WSE_USABLE_PES_W);
        m_meshHeight = std::min(m_meshHeight, WSE_USABLE_PES_H);

        if (static_cast<uint64_t>(m_meshWidth) * m_meshHeight
            > static_cast<uint64_t>(WSE_USABLE_PES_W) * WSE_USABLE_PES_H) {
            v3error("WSE: PE count "
                    << (m_meshWidth * m_meshHeight) << " exceeds usable area " << WSE_USABLE_PES_W
                    << "x" << WSE_USABLE_PES_H << ". Reduce --wse-pes.");
        }

        UINFO(2, "WSE: Partitioning " << n << " nodes into " << m_meshWidth << "x" << m_meshHeight
                                       << " mesh" << endl);

        // Phase A: Spectral embedding
        phaseA_spectralEmbedding();

        // Phase B: Memory budget enforcement
        phaseB_memoryBudget();

        // Phase C: Load balancing
        phaseC_loadBalance();

        return buildResult();
    }
};

//######################################################################
// V3WsePartition static method

WsePeMap V3WsePartition::partition(AstNetlist* netlistp, const WseDesignStats& stats) {
    UINFO(2, __FUNCTION__ << ": " << endl);
    WsePartitioner partitioner(stats);
    return partitioner.partition();
}
