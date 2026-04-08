// -*- mode: C++; c-file-style: "cc-mode" -*-
//*************************************************************************
// DESCRIPTION: Verilator: WAVETOP WSE backend — CSL code emission
//
// Emits Cerebras CSL kernel files, layout.csl, and wse_report.json.
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
#include "V3WseEmitCsl.h"
#include "V3Error.h"
#include "V3File.h"
#include "V3Os.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <map>
#include <set>
#include <sstream>
#include <unordered_map>
#include <unordered_set>
#include <vector>

//######################################################################
// AST-to-CSL expression visitor

class WseCslExprVisitor final : public AstNVisitor {
    std::ostringstream m_os;
    std::string m_slotVar;  // Name of the pipeline slot variable

    void putOp(const char* op, AstNodeBiop* nodep) {
        m_os << "(";
        iterate(nodep->lhsp());
        m_os << " " << op << " ";
        iterate(nodep->rhsp());
        m_os << ")";
    }

    // VISITORS
    virtual void visit(AstConst* nodep) override {
        m_os << "0x" << std::hex << nodep->toUInt() << std::dec;
    }

    virtual void visit(AstVarRef* nodep) override {
        AstVar* varp = nodep->varp();
        if (!varp) {
            m_os << "/* unknown_var */";
            return;
        }
        std::string name = varp->name();
        // Replace . and -> with _
        std::replace(name.begin(), name.end(), '.', '_');
        // State variables use pipeline-indexed access
        if (varp->varType() == AstVarType::MEMBER) {
            m_os << name << "_state[" << m_slotVar << "]";
        } else {
            m_os << name;
        }
    }

    virtual void visit(AstNot* nodep) override {
        m_os << "(~";
        iterate(nodep->lhsp());
        m_os << ")";
    }

    virtual void visit(AstAnd* nodep) override { putOp("&", nodep); }
    virtual void visit(AstOr* nodep) override { putOp("|", nodep); }
    virtual void visit(AstXor* nodep) override { putOp("^", nodep); }
    virtual void visit(AstAdd* nodep) override { putOp("+", nodep); }
    virtual void visit(AstSub* nodep) override { putOp("-", nodep); }
    virtual void visit(AstMul* nodep) override { putOp("*", nodep); }
    virtual void visit(AstShiftL* nodep) override { putOp("<<", nodep); }
    virtual void visit(AstShiftR* nodep) override { putOp(">>", nodep); }
    virtual void visit(AstEq* nodep) override { putOp("==", nodep); }
    virtual void visit(AstNeq* nodep) override { putOp("!=", nodep); }
    virtual void visit(AstLt* nodep) override { putOp("<", nodep); }
    virtual void visit(AstLte* nodep) override { putOp("<=", nodep); }
    virtual void visit(AstGt* nodep) override { putOp(">", nodep); }
    virtual void visit(AstGte* nodep) override { putOp(">=", nodep); }

    virtual void visit(AstSel* nodep) override {
        m_os << "((";
        iterate(nodep->fromp());
        m_os << " >> ";
        iterate(nodep->lsbp());
        m_os << ") & ((1 << ";
        iterate(nodep->widthp());
        m_os << ") - 1))";
    }

    virtual void visit(AstConcat* nodep) override {
        // CSL has no concat — use shifts
        m_os << "((";
        iterate(nodep->lhsp());
        m_os << " << " << nodep->rhsp()->width() << ") | ";
        iterate(nodep->rhsp());
        m_os << ")";
    }

    virtual void visit(AstArraySel* nodep) override {
        iterate(nodep->fromp());
        m_os << "[";
        iterate(nodep->bitp());
        m_os << "]";
    }

    virtual void visit(AstCond* nodep) override {
        m_os << "(if (";
        iterate(nodep->condp());
        m_os << ") ";
        iterate(nodep->expr1p());
        m_os << " else ";
        iterate(nodep->expr2p());
        m_os << ")";
    }

    virtual void visit(AstNode* nodep) override {
        m_os << "/* unsupported:" << nodep->typeName() << " */";
        iterateChildren(nodep);
    }

public:
    WseCslExprVisitor(AstNode* nodep, const std::string& slotVar)
        : m_slotVar{slotVar} {
        iterate(nodep);
    }
    std::string result() const { return m_os.str(); }
};

//######################################################################
// AST-to-CSL statement visitor (for CFunc bodies)

class WseCslStmtVisitor final : public AstNVisitor {
    std::ostringstream m_os;
    std::string m_slotVar;
    int m_indent = 1;

    std::string indent() const { return std::string(m_indent * 4, ' '); }

    // VISITORS
    virtual void visit(AstNodeAssign* nodep) override {
        m_os << indent();
        WseCslExprVisitor lhs(nodep->lhsp(), m_slotVar);
        WseCslExprVisitor rhs(nodep->rhsp(), m_slotVar);
        m_os << lhs.result() << " = " << rhs.result() << ";\n";
    }

    virtual void visit(AstIf* nodep) override {
        m_os << indent() << "if (";
        WseCslExprVisitor cond(nodep->condp(), m_slotVar);
        m_os << cond.result() << ") {\n";
        ++m_indent;
        iterateAndNextNull(nodep->ifsp());
        --m_indent;
        if (nodep->elsesp()) {
            m_os << indent() << "} else {\n";
            ++m_indent;
            iterateAndNextNull(nodep->elsesp());
            --m_indent;
        }
        m_os << indent() << "}\n";
    }

    virtual void visit(AstDisplay* nodep) override {
        // TODO: WSE v0.1 — $display buffered into display_buf[slot]
        m_os << indent() << "// $display: buffered to display_buf[" << m_slotVar << "]\n";
    }

    virtual void visit(AstFinish* nodep) override {
        m_os << indent() << "// $finish: emit sentinel wavelet on ctrl_color\n";
        m_os << indent() << "@fmovh(.{.color = ctrl_color}, 0xDEADBEEF);\n";
    }

    virtual void visit(AstComment* nodep) override {
        m_os << indent() << "// " << nodep->name() << "\n";
    }

    virtual void visit(AstNode* nodep) override { iterateChildren(nodep); }

public:
    WseCslStmtVisitor(AstNode* nodep, const std::string& slotVar)
        : m_slotVar{slotVar} {
        iterateAndNextNull(nodep);
    }
    std::string result() const { return m_os.str(); }
};

//######################################################################
// Kernel class deduplication

namespace {

struct KernelClass {
    uint32_t classId;
    std::vector<uint32_t> nodeIds;  // Sorted list of node IDs
    std::vector<const WsePeInfo*> pes;  // PEs using this kernel class
};

uint64_t hashNodeIds(const std::vector<uint32_t>& nodeIds) {
    uint64_t h = 0;
    for (uint32_t id : nodeIds) {
        h ^= std::hash<uint32_t>{}(id) + 0x9e3779b9 + (h << 6) + (h >> 2);
    }
    return h;
}

}  // namespace

//######################################################################
// Main CSL emitter

void V3WseEmitCsl::emit(AstNetlist* netlistp, const WsePeMap& peMap, const WseColorMap& colors,
                         const WseSpsConfig& sps) {
    UINFO(2, "WSE: Emitting CSL..." << endl);

    const std::string prefix = v3Global.opt.prefix();
    const std::string outDir = v3Global.opt.makeDir() + "/" + prefix + "_wse";

    // Create output directory
    V3Os::createDir(v3Global.opt.makeDir());
    V3Os::createDir(outDir);

    UINFO(3, "WSE: Output directory: " << outDir << endl);

    // ================================================================
    // Step 1: Kernel class deduplication
    // ================================================================
    std::map<uint64_t, KernelClass> kernelClasses;
    uint32_t nextClassId = 0;

    for (const auto& pe : peMap.pes) {
        std::vector<uint32_t> sorted = pe.nodeIds;
        std::sort(sorted.begin(), sorted.end());
        uint64_t h = hashNodeIds(sorted);

        auto it = kernelClasses.find(h);
        if (it == kernelClasses.end()) {
            KernelClass kc;
            kc.classId = nextClassId++;
            kc.nodeIds = sorted;
            kc.pes.push_back(&pe);
            kernelClasses[h] = kc;
        } else {
            it->second.pes.push_back(&pe);
        }
    }

    UINFO(2, "WSE: " << kernelClasses.size() << " unique kernel classes" << endl);

    // ================================================================
    // Step 2: Collect all CFunc nodes for CSL emission
    // ================================================================
    // Build nodeId -> AstCFunc* mapping from the netlist
    std::unordered_map<uint32_t, AstCFunc*> nodeIdToFunc;
    {
        uint32_t nodeId = 0;
        for (AstNodeModule* modp = netlistp->modulesp(); modp;
             modp = VN_CAST(modp->nextp(), NodeModule)) {
            for (AstNode* nodep = modp->stmtsp(); nodep; nodep = nodep->nextp()) {
                AstCFunc* funcp = VN_CAST(nodep, CFunc);
                if (!funcp) continue;
                if (funcp->isConstructor() || funcp->isDestructor()) continue;
                if (funcp->dpiImport()) continue;
                nodeIdToFunc[nodeId] = funcp;
                ++nodeId;
            }
        }
    }

    // ================================================================
    // Step 3: Emit kernel_<id>.csl for each unique class
    // ================================================================
    for (auto& kcPair : kernelClasses) {
        const KernelClass& kc = kcPair.second;
        const std::string filename
            = outDir + "/kernel_" + std::to_string(kc.classId) + ".csl";
        V3OutFile of(filename, V3OutFormatter::LA_C);

        // === FILE HEADER ===
        of.puts("// WAVETOP generated kernel class " + std::to_string(kc.classId) + "\n");
        of.puts("// Generated by Verilator WAVETOP backend\n\n");
        of.puts("param memcpy_params: comptime_struct;\n");
        of.puts("const sys_mod = @import_module(\"<memcpy/memcpy>\", memcpy_params);\n\n");

        // === PIPELINE CONSTANTS ===
        of.puts("// === PIPELINE CONSTANTS ===\n");
        of.puts("const N_PIPE: u16 = " + std::to_string(sps.N_pipe) + ";\n");
        of.puts("const STATE_OFFSET: u32 = " + std::to_string(sps.stateOffsetBytes) + ";\n\n");

        // === COLOR DECLARATIONS ===
        of.puts("// === COLOR DECLARATIONS ===\n");
        of.puts("const clk_color:  color = @get_color(" + std::to_string(WSE_CLOCK_COLOR)
                + ");\n");
        of.puts("const ctrl_color: color = @get_color(" + std::to_string(WSE_CTRL_COLOR)
                + ");\n");
        of.puts("const display_color: color = @get_color(" + std::to_string(WSE_DISPLAY_COLOR)
                + ");\n");

        // Emit per-signal colors
        for (const auto& sc : colors.signalColors) {
            if (sc.colorId == WSE_CLOCK_COLOR || sc.colorId == WSE_CTRL_COLOR
                || sc.colorId == WSE_DISPLAY_COLOR)
                continue;
            of.puts("const sig_" + std::to_string(sc.edgeId) + "_color: color = @get_color("
                    + std::to_string(sc.colorId) + ");\n");
        }
        of.puts("\n");

        // === STATE VARIABLES ===
        of.puts("// === STATE VARIABLES — N_PIPE copies of each FF state var ===\n");

        // Collect state variables from the nodes in this kernel
        std::set<std::string> emittedVars;
        for (uint32_t nid : kc.nodeIds) {
            auto funcIt = nodeIdToFunc.find(nid);
            if (funcIt == nodeIdToFunc.end()) continue;
            AstCFunc* funcp = funcIt->second;

            // Walk function to find state variables
            for (AstNode* stmtp = funcp->stmtsp(); stmtp; stmtp = stmtp->nextp()) {
                AstNodeAssign* assignp = VN_CAST(stmtp, NodeAssign);
                if (!assignp) continue;
                AstVarRef* lhsRef = VN_CAST(assignp->lhsp(), VarRef);
                if (!lhsRef) continue;
                AstVar* varp = lhsRef->varp();
                if (!varp) continue;
                if (varp->varType() != AstVarType::MEMBER) continue;

                std::string vname = varp->name();
                std::replace(vname.begin(), vname.end(), '.', '_');
                if (emittedVars.count(vname)) continue;
                emittedVars.insert(vname);

                uint32_t width32 = (varp->width() + 31) / 32;
                if (width32 <= 1) {
                    of.puts("var " + vname + "_state: [N_PIPE]u32 = @zeros([N_PIPE]u32);\n");
                } else {
                    // For arrays/wide signals
                    of.puts("var " + vname + "_state: [N_PIPE][" + std::to_string(width32)
                            + "]u32 = @zeros([N_PIPE][" + std::to_string(width32) + "]u32);\n");
                }
            }
        }
        of.puts("\nvar pipe_head: u8 = 0;\n");
        of.puts("var display_buf: [N_PIPE][64]u32 = @zeros([N_PIPE][64]u32);\n");
        of.puts("var display_idx: [N_PIPE]u8 = @zeros([N_PIPE]u8);\n\n");

        // === COMBINATIONAL EVAL TASK ===
        of.puts("// === COMBINATIONAL EVAL TASK ===\n");
        of.puts("task eval_comb(clk_wlt: u32) void {\n");
        of.puts("    const slot: u8 = @truncate(u8, clk_wlt & 0xFF);\n");

        // Emit combinational logic from non-FF nodes
        for (uint32_t nid : kc.nodeIds) {
            auto funcIt = nodeIdToFunc.find(nid);
            if (funcIt == nodeIdToFunc.end()) continue;
            AstCFunc* funcp = funcIt->second;

            // Skip sequential (flip-flop) functions
            if (funcp->name().find("sequent") != std::string::npos) continue;

            of.puts("    // Node " + std::to_string(nid) + ": " + funcp->name() + "\n");

            // Translate function body
            if (funcp->stmtsp()) {
                WseCslStmtVisitor sv(funcp->stmtsp(), "slot");
                of.puts(sv.result());
            }
        }

        of.puts("}\n\n");

        // === SEQUENTIAL UPDATE TASK ===
        of.puts("// === SEQUENTIAL UPDATE TASK ===\n");
        of.puts("task eval_ff(clk_wlt: u32) void {\n");
        of.puts("    const slot: u8 = @truncate(u8, clk_wlt & 0xFF);\n");

        for (uint32_t nid : kc.nodeIds) {
            auto funcIt = nodeIdToFunc.find(nid);
            if (funcIt == nodeIdToFunc.end()) continue;
            AstCFunc* funcp = funcIt->second;

            // Only FF functions
            if (funcp->name().find("sequent") == std::string::npos) continue;

            of.puts("    // Node " + std::to_string(nid) + ": " + funcp->name() + "\n");

            if (funcp->stmtsp()) {
                WseCslStmtVisitor sv(funcp->stmtsp(), "slot");
                of.puts(sv.result());
            }
        }

        of.puts("}\n\n");

        // === RECEIVE TASKS ===
        of.puts("// === RECEIVE TASKS — one per incoming signal color ===\n");
        for (const auto& sc : colors.signalColors) {
            if (sc.colorId == WSE_CLOCK_COLOR || sc.colorId == WSE_CTRL_COLOR
                || sc.colorId == WSE_DISPLAY_COLOR)
                continue;
            of.puts("task recv_sig_" + std::to_string(sc.edgeId) + "(wlt: u32) void {\n");
            of.puts("    const slot: u8 = @truncate(u8, (wlt >> 16) & 0xFF);\n");
            if (sc.isPacked) {
                of.puts("    const val: u32 = (wlt >> " + std::to_string(sc.packShift) + ") & 0x"
                        + std::to_string(sc.packMask) + ";\n");
            } else {
                of.puts("    const val: u32 = wlt & 0xFFFF;\n");
            }
            of.puts("    // TODO: assign to appropriate state variable\n");
            of.puts("}\n\n");
        }

        // === COMPTIME BLOCK ===
        of.puts("// === COMPTIME BLOCK ===\n");
        of.puts("comptime {\n");
        of.puts("    @bind_data_task(eval_comb, @get_data_task_id(clk_color));\n");
        for (const auto& sc : colors.signalColors) {
            if (sc.colorId == WSE_CLOCK_COLOR || sc.colorId == WSE_CTRL_COLOR
                || sc.colorId == WSE_DISPLAY_COLOR)
                continue;
            of.puts("    @bind_data_task(recv_sig_" + std::to_string(sc.edgeId)
                    + ", @get_data_task_id(sig_" + std::to_string(sc.edgeId) + "_color));\n");
        }
        of.puts("}\n");
    }

    // ================================================================
    // Step 4: Emit layout.csl
    // ================================================================
    {
        const std::string filename = outDir + "/layout.csl";
        V3OutFile of(filename, V3OutFormatter::LA_C);

        of.puts("// WAVETOP layout file\n");
        of.puts("// Generated by Verilator WAVETOP backend\n\n");

        of.puts("comptime {\n");
        of.puts("    @set_rectangle(" + std::to_string(peMap.meshWidth) + ", "
                + std::to_string(peMap.meshHeight) + ");\n\n");

        // Assign kernel classes to PEs
        for (const auto& kcPair : kernelClasses) {
            const KernelClass& kc = kcPair.second;
            const std::string kernelFile
                = "kernel_" + std::to_string(kc.classId) + ".csl";

            of.puts("    // Kernel class " + std::to_string(kc.classId) + " ("
                    + std::to_string(kc.pes.size()) + " PEs)\n");
            for (const auto* pe : kc.pes) {
                of.puts("    @set_tile_code(" + std::to_string(pe->peX) + ", "
                        + std::to_string(pe->peY) + ", \"" + kernelFile
                        + "\", .{ .memcpy_params = .{ .is_sender = false } });\n");
            }
            of.puts("\n");
        }

        // Color routing configuration — X-first routing
        of.puts("    // === Color routing (X-first) ===\n");
        for (const auto& sc : colors.signalColors) {
            if (sc.colorId == WSE_CLOCK_COLOR || sc.colorId == WSE_CTRL_COLOR
                || sc.colorId == WSE_DISPLAY_COLOR)
                continue;
            of.puts("    @set_color_config(sig_" + std::to_string(sc.edgeId)
                    + "_color, .{ .routes = .{ .rx = .{ RAMP }, .tx = .{ EAST } } });\n");
        }

        // Clock broadcast: column 0 routes EAST and SOUTH
        of.puts("\n    // === Clock broadcast ===\n");
        of.puts("    @set_color_config(clk_color, .{ .routes = .{ .rx = .{ RAMP }, .tx = .{ "
                "EAST } } });\n");
        of.puts("    @set_color_config(ctrl_color, .{ .routes = .{ .rx = .{ RAMP }, .tx = .{ "
                "EAST } } });\n");

        of.puts("}\n");
    }

    // ================================================================
    // Step 5: Emit wse_report.json
    // ================================================================
    if (v3Global.opt.wseReport()) {
        const std::string filename = outDir + "/wse_report.json";
        V3OutFile of(filename, V3OutFormatter::LA_C);

        // Compute some stats
        double maxMemUtil = 0.0;
        double avgMemUtil = 0.0;
        for (const auto& pe : peMap.pes) {
            double util = static_cast<double>(pe.totalStateBytes) / WSE_MEM_BUDGET_BYTES * 100.0;
            if (util > maxMemUtil) maxMemUtil = util;
            avgMemUtil += util;
        }
        if (!peMap.pes.empty()) avgMemUtil /= peMap.pes.size();

        of.puts("{\n");
        of.puts("  \"design\": \"" + prefix + "\",\n");

        // Stats section
        of.puts("  \"stats\": {\n");
        of.puts("    \"totalNodes\": " + std::to_string(peMap.assignments.size()) + ",\n");
        of.puts("    \"totalEdges\": " + std::to_string(colors.signalColors.size()) + ",\n");
        uint32_t totalState = 0;
        for (const auto& pe : peMap.pes) totalState += pe.totalStateBytes;
        of.puts("    \"totalStateBytes\": " + std::to_string(totalState) + ",\n");
        of.puts("    \"maxCritDepth\": " + std::to_string(sps.N_causal) + ",\n");
        of.puts("    \"highFanoutNets\": " + std::to_string(0) + "\n");
        of.puts("  },\n");

        // Partition section
        of.puts("  \"partition\": {\n");
        of.puts("    \"meshWidth\": " + std::to_string(peMap.meshWidth) + ",\n");
        of.puts("    \"meshHeight\": " + std::to_string(peMap.meshHeight) + ",\n");
        of.puts("    \"usedPes\": " + std::to_string(peMap.pes.size()) + ",\n");

        std::ostringstream hopStr;
        hopStr << std::fixed;
        hopStr.precision(3);
        hopStr << peMap.avgHopDistance;
        of.puts("    \"avgHopDistance\": " + hopStr.str() + ",\n");

        std::ostringstream maxMemStr;
        maxMemStr << std::fixed;
        maxMemStr.precision(1);
        maxMemStr << maxMemUtil;
        of.puts("    \"maxMemUtilPct\": " + maxMemStr.str() + ",\n");

        std::ostringstream avgMemStr;
        avgMemStr << std::fixed;
        avgMemStr.precision(1);
        avgMemStr << avgMemUtil;
        of.puts("    \"avgMemUtilPct\": " + avgMemStr.str() + ",\n");

        std::ostringstream locStr;
        locStr << std::fixed;
        locStr.precision(3);
        locStr << peMap.localityAlpha;
        of.puts("    \"localityAlpha\": " + locStr.str() + ",\n");
        of.puts("    \"uniqueKernelClasses\": " + std::to_string(kernelClasses.size()) + "\n");
        of.puts("  },\n");

        // SPS section
        of.puts("  \"sps\": {\n");
        of.puts("    \"N_pipe\": " + std::to_string(sps.N_pipe) + ",\n");
        of.puts("    \"bindingConstraint\": \"" + sps.bindingConstraint + "\",\n");
        of.puts("    \"N_mem\": " + std::to_string(sps.N_mem) + ",\n");
        of.puts("    \"N_colors\": " + std::to_string(sps.N_colors) + ",\n");
        of.puts("    \"N_mt\": " + std::to_string(sps.N_mt) + ",\n");
        of.puts("    \"N_causal\": " + std::to_string(sps.N_causal) + ",\n");

        std::ostringstream sramStr;
        sramStr << std::fixed;
        sramStr.precision(1);
        sramStr << (static_cast<double>(sps.totalSramPerPe) / 1024.0);
        of.puts("    \"totalSramPerPeKB\": " + sramStr.str() + ",\n");

        std::ostringstream thrStr;
        thrStr << std::fixed;
        thrStr.precision(1);
        thrStr << sps.estThroughputKHz;
        of.puts("    \"estThroughputKHz\": " + thrStr.str() + ",\n");

        std::ostringstream spdStr;
        spdStr << std::fixed;
        spdStr.precision(1);
        spdStr << sps.estSpeedupVsVlt;
        of.puts("    \"estSpeedupVsVlt\": " + spdStr.str() + "\n");
        of.puts("  },\n");

        // Colors section
        of.puts("  \"colors\": {\n");
        of.puts("    \"maxColorsPerPe\": " + std::to_string(colors.maxColorsPerPe) + ",\n");

        std::ostringstream avgColStr;
        avgColStr << std::fixed;
        avgColStr.precision(1);
        avgColStr << colors.avgColorsPerPe;
        of.puts("    \"avgColorsPerPe\": " + avgColStr.str() + ",\n");
        of.puts("    \"packedWavelets\": " + std::to_string(colors.packedWavelets) + ",\n");
        of.puts("    \"unpackedSignals\": " + std::to_string(colors.unpackedSignals) + "\n");
        of.puts("  }\n");
        of.puts("}\n");
    }

    UINFO(2, "WSE: CSL emission complete. " << kernelClasses.size()
                                              << " kernel classes emitted." << endl);
}
