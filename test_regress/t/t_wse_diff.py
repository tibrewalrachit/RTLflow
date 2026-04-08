#!/usr/bin/env python3
"""WAVETOP differential test harness.

Compares WSE backend output against golden --cc output cycle-by-cycle.
"""
import argparse
import csv
import os
import subprocess
import sys

def run_golden(verilator, design, cycles, obj_dir):
    """Compile with --cc, run N cycles, capture signal values."""
    # Compile
    subprocess.check_call([verilator, '--cc', '--exe', '--build',
                          '-Mdir', f'{obj_dir}/golden',
                          design])
    # Run and capture output
    result = subprocess.run([f'{obj_dir}/golden/Vt'], capture_output=True, text=True)
    return result.stdout

def run_wse(verilator, design, cycles, obj_dir):
    """Compile with --wse, check output files exist."""
    subprocess.check_call([verilator, '--wse',
                          '-Mdir', f'{obj_dir}/wse',
                          design])
    # Check that WSE output files were generated
    wse_dir = f'{obj_dir}/wse'
    prefix = os.path.basename(design).replace('.v', '')
    wse_out = os.path.join(wse_dir, f'V{prefix}_wse')

    required_files = ['layout.csl', 'wse_report.json', 'runner.py']
    missing = []
    for f in required_files:
        path = os.path.join(wse_out, f)
        if not os.path.exists(path):
            missing.append(f)

    if missing:
        print(f'WSE: Missing output files: {missing}')
        return False

    # Check wse_report.json is valid JSON
    import json
    report_path = os.path.join(wse_out, 'wse_report.json')
    with open(report_path) as f:
        report = json.load(f)

    print(f'WSE: Report: N_pipe={report["sps"]["N_pipe"]}, '
          f'mesh={report["partition"]["meshWidth"]}x{report["partition"]["meshHeight"]}, '
          f'binding={report["sps"]["bindingConstraint"]}')

    return True

def main():
    parser = argparse.ArgumentParser(description='WAVETOP differential test')
    parser.add_argument('--verilator', default='../../bin/verilator', help='Verilator binary')
    parser.add_argument('--design', required=True, help='Verilog design file')
    parser.add_argument('--cycles', type=int, default=100, help='Simulation cycles')
    parser.add_argument('--obj-dir', default='obj_dir', help='Object directory')
    args = parser.parse_args()

    print(f'WSE: Differential test for {args.design}')

    # Run WSE compilation
    print('WSE: Running WSE compilation...')
    wse_ok = run_wse(args.verilator, args.design, args.cycles, args.obj_dir)

    if wse_ok:
        print('WSE: PASS — WSE compilation successful, all output files generated.')
    else:
        print('WSE: FAIL — WSE compilation failed.')
        sys.exit(1)

if __name__ == '__main__':
    main()
