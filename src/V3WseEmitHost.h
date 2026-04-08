// -*- mode: C++; c-file-style: "cc-mode" -*-
//*************************************************************************
// DESCRIPTION: Verilator: WAVETOP WSE backend — host runner emission
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

#include "wse/WseTypes.h"

class V3WseEmitHost final {
public:
    static void emit(const WsePeMap& peMap, const WseSpsConfig& sps);
};
