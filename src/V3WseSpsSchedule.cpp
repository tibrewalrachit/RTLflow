// -*- mode: C++; c-file-style: "cc-mode" -*-
//*************************************************************************
// DESCRIPTION: Verilator: WAVETOP WSE backend — SPS pipeline scheduling
//
// Computes the pipeline depth N_pipe as the minimum of four independent
// bounds: SRAM, colors, microthreads, and causality.
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
#include "V3WseSpsSchedule.h"
#include "V3Error.h"

#include <algorithm>
#include <cmath>

//######################################################################
// V3WseSpsSchedule static method

WseSpsConfig V3WseSpsSchedule::schedule(const WsePeMap& peMap, const WseColorMap& colorMap,
                                         const WseDesignStats& stats) {
    UINFO(2, "WSE: Computing SPS schedule..." << endl);

    WseSpsConfig sps;
    const std::string wseArch = v3Global.opt.wseArch();

    // Bound A: SRAM
    // N_mem = WSE_MEM_BUDGET_BYTES / maxStatePerPe
    uint32_t maxStatePerPe = 0;
    for (const auto& pe : peMap.pes) {
        if (pe.totalStateBytes > maxStatePerPe) maxStatePerPe = pe.totalStateBytes;
    }
    sps.N_mem = (maxStatePerPe > 0) ? WSE_MEM_BUDGET_BYTES / maxStatePerPe : 100;

    // Bound B: Colors (reserve 4 for clock/ctrl/display/memcpy)
    uint32_t colorsAvail = (wseArch == "wse3") ? 20 : 18;
    sps.N_colors = (colorMap.maxColorsPerPe > 0)
                       ? std::max(1u, colorsAvail / colorMap.maxColorsPerPe)
                       : 100;

    // Bound C: Microthreads (reserve 1 for memcpy)
    sps.N_mt = (wseArch == "wse3") ? 8 : 7;

    // Bound D: Causality — limited by critical path depth
    sps.N_causal = (stats.maxCritDepth > 0) ? stats.maxCritDepth : 1;

    // N_pipe = min of all bounds
    sps.N_pipe = std::min({sps.N_mem, sps.N_colors, sps.N_mt, sps.N_causal});
    if (sps.N_pipe < 1) sps.N_pipe = 1;

    // Determine binding constraint
    if (sps.N_pipe == sps.N_mem) {
        sps.bindingConstraint = "mem";
    } else if (sps.N_pipe == sps.N_colors) {
        sps.bindingConstraint = "colors";
    } else if (sps.N_pipe == sps.N_mt) {
        sps.bindingConstraint = "microthreads";
    } else {
        sps.bindingConstraint = "causality";
    }

    // User override
    if (v3Global.opt.wseNpipe() > 0) {
        sps.N_pipe = v3Global.opt.wseNpipe();
        sps.bindingConstraint = "user-override";
    }

    // Warning for N_pipe == 1
    if (sps.N_pipe == 1) {
        v3info("WSE: Pipeline depth is 1 -- communication will not be hidden.");
    }

    // Compute state offset and total SRAM per PE
    sps.stateOffsetBytes = maxStatePerPe;
    sps.totalSramPerPe = maxStatePerPe * sps.N_pipe;

    // Estimate throughput
    // Each PE processes one cycle per estCycles (in PE clock cycles)
    // With N_pipe slots, throughput = N_pipe * WSE_CLOCK_GHZ * 1e6 / maxEstCycles
    uint32_t maxEstCycles = 0;
    for (const auto& pe : peMap.pes) {
        if (pe.estCycles > maxEstCycles) maxEstCycles = pe.estCycles;
    }
    if (maxEstCycles > 0) {
        sps.estThroughputKHz
            = (static_cast<double>(sps.N_pipe) * WSE_CLOCK_GHZ * 1.0e6) / maxEstCycles;
    } else {
        sps.estThroughputKHz = 0.0;
    }

    // Estimate speedup vs Verilator single-threaded
    // Rough baseline: Verilator does ~100K cycles/sec for large designs
    sps.estSpeedupVsVlt = sps.estThroughputKHz / 100.0;

    UINFO(2, "WSE: SPS schedule: N_pipe=" << sps.N_pipe << " binding=" << sps.bindingConstraint
                                           << " N_mem=" << sps.N_mem
                                           << " N_colors=" << sps.N_colors
                                           << " N_mt=" << sps.N_mt
                                           << " N_causal=" << sps.N_causal << endl);
    UINFO(2, "WSE: Est throughput=" << sps.estThroughputKHz
                                    << "KHz speedup=" << sps.estSpeedupVsVlt << "x" << endl);

    return sps;
}
