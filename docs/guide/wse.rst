WAVETOP: Cerebras WSE Backend
=============================

WAVETOP compiles RTL designs to run on the Cerebras Wafer-Scale Engine (WSE)
using Spatial Pipeline Simulation (SPS).

Prerequisites
-------------

* ``CEREBRAS_SDK_ROOT`` environment variable must point to the Cerebras SDK
* ``cslc``: ``$CEREBRAS_SDK_ROOT/bin/cslc``
* Minimum SDK version: 1.3 (WSE-2), 1.4 recommended (WSE-3)

Usage
-----

.. code-block:: bash

    verilator --wse design.v

Command-line Options
--------------------

``--wse``
    Enable WSE backend. Generates CSL files instead of C++.

``--wse-arch <wse2|wse3>``
    Target architecture. Default: ``wse3``.

``--wse-pes N``
    Maximum PEs to use. 0 = auto-size. Default: 0.

``--wse-npipe N``
    Force pipeline depth. 0 = auto. Default: 0.

``--wse-width W``
    Mesh rectangle width. 0 = auto. Default: 0.

``--wse-height H``
    Mesh rectangle height. 0 = auto. Default: 0.

``--wse-report``
    Emit ``wse_report.json`` with partition statistics. Default: on.

Known Limitations (v0.1)
------------------------

* DPI imports silently ignored (WSE_COMPAT warning emitted)
* C++ testbenches not supported (Verilog-only)
* ``$dumpvars`` / VCD tracing not supported
* Combinational loops cause error (no unrolling)
* Multi-clock designs: all clocks treated as synchronous
* FP64: WSE supports FP32/FP16 only
* ``--wse-arch wse3`` flag exists but WSE-2 semantics implemented first
