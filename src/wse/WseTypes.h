// -*- mode: C++; c-file-style: "cc-mode" -*-
//*************************************************************************
// DESCRIPTION: Verilator: WAVETOP WSE backend — shared types
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

#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <unordered_map>

// Forward declarations for Verilator AST types
class AstCFunc;
class AstVar;

// ========================================================================
// WSE hardware constants
// ========================================================================

constexpr uint32_t WSE_USABLE_PES_W      = 750;
constexpr uint32_t WSE_USABLE_PES_H      = 994;
constexpr uint32_t WSE_MEM_TOTAL_KB      = 48;
constexpr uint32_t WSE_MEM_OVERHEAD_KB   = 4;
constexpr uint32_t WSE_MEM_BUDGET_BYTES  = (WSE_MEM_TOTAL_KB - WSE_MEM_OVERHEAD_KB) * 1024;
constexpr uint32_t WSE_COLORS_TOTAL      = 24;
constexpr uint32_t WSE_COLORS_RESERVED   = 4;
constexpr uint32_t WSE_COLORS_USABLE     = WSE_COLORS_TOTAL - WSE_COLORS_RESERVED;
constexpr uint8_t  WSE_CLOCK_COLOR       = 20;
constexpr uint8_t  WSE_CTRL_COLOR        = 19;
constexpr uint8_t  WSE_DISPLAY_COLOR     = 18;
constexpr uint32_t WSE_MICROTHREADS      = 9;
constexpr uint32_t WSE_MICROTHREADS_WSE3 = 9;
constexpr double   WSE_CLOCK_GHZ         = 0.875;
constexpr uint32_t WSE_OPS_PER_CYCLE     = 4;

// ========================================================================
// Core data structures
// ========================================================================

struct WseNode {
    AstCFunc* funcp;
    uint32_t  nodeId;
    uint32_t  estCycles;
    uint32_t  stateBytes;
    bool      isFlipFlop;
    bool      isMem;
    int       critDepth;
};

struct WseEdge {
    uint32_t srcNodeId;
    uint32_t dstNodeId;
    AstVar*  varp;
    uint32_t widthBits;
    bool     isHighFanout;
};

struct WseDesignStats {
    std::vector<WseNode> nodes;
    std::vector<WseEdge> edges;
    uint32_t totalNodes;
    uint32_t totalEdges;
    uint32_t totalStateBytes;
    uint32_t maxCritDepth;
    uint32_t highFanoutNets;
    uint32_t crossModuleEdges;
    double   avgEdgesPerNode;
};

struct WsePeAssignment {
    uint32_t nodeId;
    uint32_t peX;
    uint32_t peY;
};

struct WsePeInfo {
    uint32_t peX;
    uint32_t peY;
    std::vector<uint32_t> nodeIds;
    uint32_t totalStateBytes;
    uint32_t estCycles;
};

struct WsePeMap {
    std::vector<WsePeAssignment> assignments;
    std::vector<WsePeInfo>       pes;
    uint32_t meshWidth;
    uint32_t meshHeight;
    double   avgHopDistance;
    double   localityAlpha;
};

struct WseSignalColor {
    uint32_t edgeId;
    uint8_t  colorId;
    bool     isPacked;
    uint32_t packShift;
    uint32_t packMask;
};

struct WseColorMap {
    std::vector<WseSignalColor> signalColors;
    uint32_t maxColorsPerPe;
    double   avgColorsPerPe;
    uint32_t packedWavelets;
    uint32_t unpackedSignals;
};

struct WseSpsConfig {
    uint32_t N_pipe;
    uint32_t N_mem, N_colors, N_mt, N_causal;
    std::string bindingConstraint;
    uint32_t stateOffsetBytes;
    uint32_t totalSramPerPe;
    double   estThroughputKHz;
    double   estSpeedupVsVlt;
};
