// -*- mode: C++; c-file-style: "cc-mode" -*-
//*************************************************************************
// DESCRIPTION: Verilator: WAVETOP WSE backend — design partitioning
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

#include "V3Ast.h"
#include "wse/WseTypes.h"

class V3WsePartition final {
public:
    static WsePeMap partition(AstNetlist* netlistp, const WseDesignStats& stats);
};
