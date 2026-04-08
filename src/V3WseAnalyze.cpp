// -*- mode: C++; c-file-style: "cc-mode" -*-
//*************************************************************************
// DESCRIPTION: Verilator: WAVETOP WSE backend — design analysis pass
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
#include "V3Ast.h"
#include "V3WseAnalyze.h"
#include "V3Error.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <queue>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>

//######################################################################
// Visitor to count expression nodes inside a CFunc body

class WseExprCountVisitor final : public AstNVisitor {
    uint32_t m_exprCount = 0;

    virtual void visit(AstNodeMath* nodep) override {
        ++m_exprCount;
        iterateChildren(nodep);
    }
    virtual void visit(AstNode* nodep) override { iterateChildren(nodep); }

public:
    explicit WseExprCountVisitor(AstNode* nodep) { iterate(nodep); }
    uint32_t count() const { return m_exprCount; }
};

//######################################################################
// Visitor to count state (written MEMBER) variables and detect FFs/mem

class WseStateCountVisitor final : public AstNVisitor {
    uint32_t m_stateBytes = 0;
    bool m_hasFlipFlop = false;
    bool m_hasMem = false;

    virtual void visit(AstVarRef* nodep) override {
        if (nodep->access() == VAccess::WRITE || nodep->access() == VAccess::READWRITE) {
            AstVar* varp = nodep->varp();
            if (varp && varp->varType() == AstVarType::MEMBER) {
                // Each 32-bit variable = 4 bytes
                uint32_t bytes = (varp->width() + 31) / 32 * 4;
                m_stateBytes += bytes;
            }
        }
        iterateChildren(nodep);
    }
    virtual void visit(AstNode* nodep) override { iterateChildren(nodep); }

public:
    explicit WseStateCountVisitor(AstNode* nodep) { iterate(nodep); }
    uint32_t stateBytes() const { return m_stateBytes; }
    bool hasFlipFlop() const { return m_hasFlipFlop; }
    bool hasMem() const { return m_hasMem; }
};

//######################################################################
// Visitor to collect variable references (reads/writes) per CFunc

class WseVarRefVisitor final : public AstNVisitor {
    std::set<AstVar*> m_reads;
    std::set<AstVar*> m_writes;

    virtual void visit(AstVarRef* nodep) override {
        AstVar* varp = nodep->varp();
        if (!varp) return;
        if (nodep->access() == VAccess::WRITE) {
            m_writes.insert(varp);
        } else if (nodep->access() == VAccess::READ) {
            m_reads.insert(varp);
        } else if (nodep->access() == VAccess::READWRITE) {
            m_reads.insert(varp);
            m_writes.insert(varp);
        }
        iterateChildren(nodep);
    }
    virtual void visit(AstNode* nodep) override { iterateChildren(nodep); }

public:
    explicit WseVarRefVisitor(AstNode* nodep) { iterate(nodep); }
    const std::set<AstVar*>& reads() const { return m_reads; }
    const std::set<AstVar*>& writes() const { return m_writes; }
};

//######################################################################
// Main analysis visitor — walks the netlist and builds WseDesignStats

class WseAnalyzeVisitor final : public AstNVisitor {
    // STATE
    std::vector<WseNode> m_nodes;
    std::vector<WseEdge> m_edges;
    uint32_t m_nextNodeId = 0;

    // Map from AstCFunc* -> nodeId
    std::unordered_map<AstCFunc*, uint32_t> m_funcToNodeId;
    // Map from AstVar* -> set of CFunc nodeIds that write it
    std::unordered_map<AstVar*, std::set<uint32_t>> m_varWriters;
    // Map from AstVar* -> set of CFunc nodeIds that read it
    std::unordered_map<AstVar*, std::set<uint32_t>> m_varReaders;
    // Map from AstCFunc* -> its scope for module boundary detection
    std::unordered_map<uint32_t, AstScope*> m_nodeScopes;

    // METHODS

    // Phase 1: Collect all CFuncs and build nodes
    void collectNodes(AstNetlist* netlistp) {
        // Iterate through all modules and their CFuncs
        for (AstNodeModule* modp = netlistp->modulesp(); modp;
             modp = VN_CAST(modp->nextp(), NodeModule)) {
            for (AstNode* nodep = modp->stmtsp(); nodep; nodep = nodep->nextp()) {
                AstCFunc* funcp = VN_CAST(nodep, CFunc);
                if (!funcp) continue;
                // Skip special functions (constructors, destructors, etc.)
                if (funcp->isConstructor() || funcp->isDestructor()) continue;
                if (funcp->dpiImport()) {
                    v3info("WSE: DPI import " << funcp->name()
                                               << " ignored. Results may differ.");
                    continue;
                }

                uint32_t nodeId = m_nextNodeId++;
                m_funcToNodeId[funcp] = nodeId;
                m_nodeScopes[nodeId] = funcp->scopep();

                // Count expression nodes for cycle estimate
                WseExprCountVisitor exprCounter(funcp);
                uint32_t estCycles = exprCounter.count() * 3;

                // Count state bytes
                WseStateCountVisitor stateCounter(funcp);

                // Detect FF: functions with "sequent" or "settle" in name,
                // or that contain delayed assignments
                bool isFF = (funcp->name().find("sequent") != std::string::npos);
                bool isMem = (funcp->name().find("mem") != std::string::npos);

                WseNode node;
                node.funcp = funcp;
                node.nodeId = nodeId;
                node.estCycles = estCycles;
                node.stateBytes = stateCounter.stateBytes();
                node.isFlipFlop = isFF;
                node.isMem = isMem;
                node.critDepth = 0;
                m_nodes.push_back(node);

                // Collect var refs
                WseVarRefVisitor varRefs(funcp);
                for (AstVar* varp : varRefs.writes()) { m_varWriters[varp].insert(nodeId); }
                for (AstVar* varp : varRefs.reads()) { m_varReaders[varp].insert(nodeId); }
            }
        }
    }

    // Phase 2: Build edges from var writer->reader relationships
    void buildEdges() {
        std::set<std::pair<uint32_t, uint32_t>> edgeSet;  // Deduplicate
        for (auto& pair : m_varWriters) {
            AstVar* varp = pair.first;
            const auto& writers = pair.second;
            auto it = m_varReaders.find(varp);
            if (it == m_varReaders.end()) continue;
            const auto& readers = it->second;

            uint32_t widthBits = varp ? varp->width() : 32;

            for (uint32_t wrId : writers) {
                for (uint32_t rdId : readers) {
                    if (wrId == rdId) continue;  // Skip self-edges
                    auto key = std::make_pair(wrId, rdId);
                    if (edgeSet.count(key)) continue;
                    edgeSet.insert(key);

                    WseEdge edge;
                    edge.srcNodeId = wrId;
                    edge.dstNodeId = rdId;
                    edge.varp = varp;
                    edge.widthBits = widthBits;
                    edge.isHighFanout = false;  // Set in phase 3
                    m_edges.push_back(edge);
                }
            }
        }
    }

    // Phase 3: Mark high-fanout nets (>50 distinct consumers)
    void markHighFanout() {
        std::unordered_map<AstVar*, uint32_t> fanoutCount;
        for (auto& pair : m_varReaders) {
            fanoutCount[pair.first] = static_cast<uint32_t>(pair.second.size());
        }
        for (auto& edge : m_edges) {
            if (edge.varp && fanoutCount[edge.varp] > 50) { edge.isHighFanout = true; }
        }
    }

    // Phase 4: Compute critical path depth via topological sort
    void computeCritDepth() {
        if (m_nodes.empty()) return;

        uint32_t n = static_cast<uint32_t>(m_nodes.size());
        std::vector<std::vector<uint32_t>> adj(n);
        std::vector<uint32_t> inDegree(n, 0);

        for (const auto& edge : m_edges) {
            if (edge.srcNodeId < n && edge.dstNodeId < n) {
                adj[edge.srcNodeId].push_back(edge.dstNodeId);
                ++inDegree[edge.dstNodeId];
            }
        }

        // Kahn's algorithm with depth tracking
        std::queue<uint32_t> q;
        std::vector<int> depth(n, 1);
        for (uint32_t i = 0; i < n; ++i) {
            if (inDegree[i] == 0) q.push(i);
        }

        uint32_t visited = 0;
        while (!q.empty()) {
            uint32_t u = q.front();
            q.pop();
            ++visited;
            for (uint32_t v : adj[u]) {
                depth[v] = std::max(depth[v], depth[u] + 1);
                if (--inDegree[v] == 0) q.push(v);
            }
        }

        if (visited < n) {
            // Combinational loop detected
            std::vector<uint32_t> loopNodes;
            for (uint32_t i = 0; i < n; ++i) {
                if (inDegree[i] > 0) loopNodes.push_back(i);
            }
            std::string nodeList;
            for (size_t i = 0; i < loopNodes.size() && i < 10; ++i) {
                if (i > 0) nodeList += ", ";
                nodeList += std::to_string(loopNodes[i]);
            }
            v3error("WSE: Combinational loop detected through nodes [" << nodeList << "].");
        }

        for (uint32_t i = 0; i < n; ++i) { m_nodes[i].critDepth = depth[i]; }
    }

    // Phase 5: Count cross-module edges
    uint32_t countCrossModuleEdges() {
        uint32_t count = 0;
        for (const auto& edge : m_edges) {
            auto srcIt = m_nodeScopes.find(edge.srcNodeId);
            auto dstIt = m_nodeScopes.find(edge.dstNodeId);
            if (srcIt != m_nodeScopes.end() && dstIt != m_nodeScopes.end()) {
                if (srcIt->second != dstIt->second) ++count;
            }
        }
        return count;
    }

    // VISITORS — required for AstNVisitor but not used (we traverse manually)
    virtual void visit(AstNode* nodep) override { iterateChildren(nodep); }

public:
    WseDesignStats analyze(AstNetlist* netlistp) {
        UINFO(2, "WSE: Analyzing design..." << endl);

        collectNodes(netlistp);
        UINFO(3, "WSE: Found " << m_nodes.size() << " nodes" << endl);

        buildEdges();
        UINFO(3, "WSE: Found " << m_edges.size() << " edges" << endl);

        markHighFanout();
        computeCritDepth();

        // Build stats
        WseDesignStats stats;
        stats.nodes = m_nodes;
        stats.edges = m_edges;
        stats.totalNodes = static_cast<uint32_t>(m_nodes.size());
        stats.totalEdges = static_cast<uint32_t>(m_edges.size());

        uint32_t totalState = 0;
        uint32_t maxDepth = 0;
        uint32_t highFanout = 0;
        for (const auto& node : m_nodes) {
            totalState += node.stateBytes;
            if (static_cast<uint32_t>(node.critDepth) > maxDepth) {
                maxDepth = static_cast<uint32_t>(node.critDepth);
            }
        }
        for (const auto& edge : m_edges) {
            if (edge.isHighFanout) ++highFanout;
        }

        stats.totalStateBytes = totalState;
        stats.maxCritDepth = maxDepth;
        stats.highFanoutNets = highFanout;
        stats.crossModuleEdges = countCrossModuleEdges();
        stats.avgEdgesPerNode
            = m_nodes.empty() ? 0.0 : static_cast<double>(m_edges.size()) / m_nodes.size();

        UINFO(2, "WSE: Analysis complete. Nodes=" << stats.totalNodes
                                                   << " Edges=" << stats.totalEdges
                                                   << " State=" << stats.totalStateBytes
                                                   << "B CritDepth=" << stats.maxCritDepth << endl);

        return stats;
    }
};

//######################################################################
// V3WseAnalyze static method

WseDesignStats V3WseAnalyze::analyze(AstNetlist* netlistp) {
    UINFO(2, __FUNCTION__ << ": " << endl);
    WseAnalyzeVisitor visitor;
    return visitor.analyze(netlistp);
}
