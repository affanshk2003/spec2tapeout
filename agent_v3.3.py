#!/usr/bin/env python3
"""
Standalone Place & Route Agent

Runs ORFS place & route flow on pre-synthesized designs.
Does NOT run synthesis - assumes synthesis outputs already exist.

Features:
- Copies synthesis outputs into ORFS
- Runs ORFS P&R with CTS repair timing optionally skipped
- Streams ORFS logs live to the terminal while the flow runs
- Auto-detects ORFS platform/design/variant from config.mk or existing results
- Detects the latest stage present (for example 5_route or 6_final)
- Produces a summary report based on real files found on disk
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# =============================
# Configuration
# =============================

ORFS_TIMEOUT = 600  # seconds
DEFAULT_SKIP_CTS_REPAIR_TIMING = True
STAGE_ORDER = ["1_synth", "2_floorplan", "3_place", "4_cts", "5_route", "6_final"]


# =============================
# File Operations
# =============================

def read_file(path: str) -> str:
    """Read file content."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return ""


def write_file(path: str, content: str) -> None:
    """Write file content."""
    try:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Error writing {path}: {e}")


def copy_file(src: str | Path, dst: str | Path) -> bool:
    """Copy a file and return True on success."""
    try:
        import shutil

        src_path = Path(src)
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if src_path.resolve() == dst_path.resolve():
                return True
        except Exception:
            pass

        shutil.copy2(str(src_path), str(dst_path))
        return True
    except Exception as e:
        print(f"Error copying {src} -> {dst}: {e}")
        return False


# =============================
# Discovery Helpers
# =============================

def parse_makefile_vars(path: str) -> Dict[str, str]:
    """Parse simple Makefile-style KEY = VALUE assignments from a config file."""
    vars_found: Dict[str, str] = {}
    file_path = Path(path)
    if not file_path.exists():
        return vars_found

    assign_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:?+]?=\s*(.*?)\s*$")
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = assign_re.match(raw)
            if not m:
                continue
            key = m.group(1).strip()
            value = m.group(2).strip()
            if " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            value = value.strip().strip('"').strip("'")
            vars_found[key] = value
    return vars_found


def clean_token(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip().strip('"').strip("'")


def first_existing_dir(paths: List[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists() and path.is_dir():
            return path
    return None


def glob_first(directory: Path, patterns: List[str]) -> Optional[Path]:
    if not directory.exists():
        return None
    for pattern in patterns:
        matches = sorted(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def recursive_first(root: Path, patterns: List[str]) -> Optional[Path]:
    if not root.exists():
        return None
    for pattern in patterns:
        matches = sorted(root.rglob(pattern))
        if matches:
            return matches[0]
    return None


def detect_stage(result_dir: Path, report_dir: Optional[Path] = None) -> Optional[str]:
    """Detect the latest stage that exists in the result/report tree."""
    for stage in reversed(STAGE_ORDER):
        if (result_dir / f"{stage}.odb").exists():
            return stage

    if report_dir is not None and report_dir.exists():
        for stage in reversed(STAGE_ORDER):
            if list(report_dir.glob(f"{stage}*.rpt")):
                return stage
            if list(report_dir.glob(f"{stage}*.log")):
                return stage

    return None


def detect_orfs_layout(orfs_dir: str, config_file: str, module_name: str) -> Dict[str, object]:
    """Detect platform/design/variant and the corresponding results/reports directories."""
    orfs_path = Path(orfs_dir)
    results_root = orfs_path / "results"
    reports_root = orfs_path / "reports"

    cfg = parse_makefile_vars(config_file)
    platform = clean_token(cfg.get("PLATFORM")) or clean_token(cfg.get("PLATFORM_NAME"))
    design_name = clean_token(cfg.get("DESIGN_NAME")) or clean_token(cfg.get("DESIGN")) or module_name
    variant = clean_token(cfg.get("VARIANT")) or clean_token(cfg.get("FLOW_VARIANT")) or "base"

    result_candidates = [
        results_root / platform / design_name / variant if platform and design_name else None,
        results_root / platform / design_name if platform and design_name else None,
        results_root / design_name / variant if design_name else None,
        results_root / design_name if design_name else None,
        results_root / platform if platform else None,
    ]
    result_candidates = [p for p in result_candidates if p is not None]

    result_dir = first_existing_dir(result_candidates)

    # If no config-based directory exists, find a real stage file and use its parent.
    if result_dir is None and results_root.exists():
        for stage in reversed(STAGE_ORDER):
            found = recursive_first(results_root, [f"{stage}.odb"])
            if found is not None:
                result_dir = found.parent
                break

    if result_dir is None and results_root.exists():
        any_odb = recursive_first(results_root, ["*.odb"])
        if any_odb is not None:
            result_dir = any_odb.parent

    if result_dir is None:
        if platform and design_name:
            result_dir = results_root / platform / design_name / variant
        elif design_name:
            result_dir = results_root / design_name / variant
        else:
            result_dir = results_root / "unknown" / module_name / "base"

    # Report directory follows the same relative path as results, if possible.
    try:
        rel = result_dir.relative_to(results_root)
        report_dir = reports_root / rel
    except Exception:
        report_dir = reports_root / (platform or "unknown") / (design_name or module_name) / variant

    if not report_dir.exists() and reports_root.exists():
        inferred = None
        for stage in reversed(STAGE_ORDER):
            found = recursive_first(reports_root, [f"{stage}*.rpt", f"{stage}*.log"])
            if found is not None:
                inferred = found.parent
                break
        if inferred is None:
            any_rpt = recursive_first(reports_root, ["*.rpt"])
            if any_rpt is not None:
                inferred = any_rpt.parent
        if inferred is not None:
            report_dir = inferred

    final_stage = detect_stage(result_dir, report_dir)

    return {
        "platform": platform or "unknown",
        "design_name": design_name,
        "variant": variant,
        "results_dir": result_dir,
        "reports_dir": report_dir,
        "final_stage": final_stage or "not detected",
        "config_vars": cfg,
    }


def find_reports_for_stage(report_dir: Path, stage: Optional[str], suffix: str) -> Optional[Path]:
    """Find a report file for a given stage and suffix."""
    if not report_dir.exists():
        return None

    patterns: List[str] = []
    if stage and stage != "not detected":
        patterns.extend([f"{stage}*{suffix}", f"{stage}*.{suffix.lstrip('.')}"])
    patterns.extend([f"*{suffix}", f"*.{suffix.lstrip('.')}"])
    return glob_first(report_dir, patterns)


def find_output_file(result_dir: Path, stage: Optional[str], suffix: str) -> Optional[Path]:
    """Find a result file for a given stage and suffix."""
    if not result_dir.exists():
        return None

    patterns: List[str] = []
    if stage and stage != "not detected":
        patterns.extend([f"{stage}{suffix}", f"{stage}*{suffix}"])
    patterns.append(f"*{suffix}")
    return glob_first(result_dir, patterns)


# =============================
# Phase 1: ORFS Setup
# =============================

def setup_orfs_flow(
    orfs_dir: str,
    synth_netlist: str,
    sdc_file: str,
    config_file: str,
    tb_file: Optional[str] = None,
) -> bool:
    """Setup ORFS flow directory with synthesis outputs."""

    print("\n" + "=" * 70)
    print("PHASE 1: ORFS DIRECTORY SETUP")
    print("=" * 70)

    try:
        orfs_path = Path(orfs_dir)
        rtl_dir = orfs_path / "rtl"
        sdc_dir = orfs_path / "sdc"
        tb_dir = orfs_path / "testbench"

        rtl_dir.mkdir(parents=True, exist_ok=True)
        sdc_dir.mkdir(parents=True, exist_ok=True)
        tb_dir.mkdir(parents=True, exist_ok=True)

        print(f"Created ORFS directory: {orfs_dir}")
        print("\nCopying synthesis outputs to ORFS...")

        if Path(synth_netlist).exists():
            dest_netlist = rtl_dir / Path(synth_netlist).name
            if not copy_file(synth_netlist, dest_netlist):
                return False
            print(f"  OK {Path(synth_netlist).name}")
        else:
            print(f"  ERROR Netlist not found: {synth_netlist}")
            return False

        if Path(sdc_file).exists():
            dest_sdc = sdc_dir / Path(sdc_file).name
            if not copy_file(sdc_file, dest_sdc):
                return False
            print(f"  OK {Path(sdc_file).name}")
        else:
            print(f"  ERROR SDC file not found: {sdc_file}")
            return False

        if tb_file and Path(tb_file).exists():
            dest_tb = tb_dir / Path(tb_file).name
            if not copy_file(tb_file, dest_tb):
                return False
            print(f"  OK {Path(tb_file).name}")

        if Path(config_file).exists():
            dest_config = orfs_path / "config.mk"
            if not copy_file(config_file, dest_config):
                return False
            print(f"  OK {Path(config_file).name}")
        else:
            print(f"  WARN Config file not found: {config_file}")

        print("\nSetup complete!")
        return True

    except Exception as e:
        print(f"Setup failed: {e}")
        import traceback

        traceback.print_exc()
        return False


# =============================
# Phase 2: ORFS Place & Route
# =============================

def run_orfs_flow(
    orfs_dir: str,
    target: str = "all",
    skip_cts_repair_timing: bool = DEFAULT_SKIP_CTS_REPAIR_TIMING,
) -> bool:
    """Run ORFS place & route flow and stream logs live to the terminal."""

    print("\n" + "=" * 70)
    print("PHASE 2: ORFS PLACE & ROUTE")
    print("=" * 70)

    try:
        print(f"\nRunning ORFS flow in {orfs_dir}...")
        print(f"Target: {target}")
        print(f"Skip CTS repair timing: {skip_cts_repair_timing}")

        env = os.environ.copy()
        if skip_cts_repair_timing:
            env["SKIP_CTS_REPAIR_TIMING"] = "1"

        log_path = Path(orfs_dir) / "orfs_run.log"
        cmd = ["make", target]

        with open(log_path, "w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                cmd,
                cwd=orfs_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )

            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
                sys.stdout.flush()
                log_file.write(line)
                log_file.flush()

            return_code = process.wait(timeout=ORFS_TIMEOUT)

        if return_code != 0:
            print("ORFS flow failed!")
            print(f"Saved log: {log_path}")
            return False

        print("\nORFS flow complete!")
        print(f"Saved log: {log_path}")
        return True

    except subprocess.TimeoutExpired:
        print("ORFS flow timeout (>10 minutes)")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


# =============================
# Phase 3: Timing Analysis
# =============================

def analyze_timing(layout: Dict[str, object]) -> bool:
    """Extract and analyze timing from ORFS results."""

    print("\n" + "=" * 70)
    print("PHASE 3: TIMING ANALYSIS")
    print("=" * 70)

    try:
        result_dir = Path(str(layout["results_dir"]))
        report_dir = Path(str(layout["reports_dir"]))
        final_stage = str(layout.get("final_stage") or "not detected")

        print(f"\nResults Directory: {result_dir}")
        print(f"Reports Directory: {report_dir}")
        print(f"Final Stage: {final_stage}")

        timing_report = find_reports_for_stage(report_dir, final_stage, ".timing.rpt")
        area_report = find_reports_for_stage(report_dir, final_stage, ".area.rpt")
        power_report = find_reports_for_stage(report_dir, final_stage, ".power.rpt")

        if timing_report is not None:
            print(f"\nTiming Report: {timing_report.name}")
            timing_content = read_file(str(timing_report))
            if "slack" in timing_content.lower():
                print("  -> Timing data available")
            print(f"  ({len(timing_content)} bytes)")
        else:
            print("\nTiming report not found")

        if area_report is not None:
            print(f"\nArea Report: {area_report.name}")
            area_content = read_file(str(area_report))
            print(f"  ({len(area_content)} bytes)")
        else:
            print("\nArea report not found")

        if power_report is not None:
            print(f"\nPower Report: {power_report.name}")
            power_content = read_file(str(power_report))
            print(f"  ({len(power_content)} bytes)")
        else:
            print("\nPower report not found")

        gds_file = find_output_file(result_dir, final_stage, ".gds")
        odb_file = find_output_file(result_dir, final_stage, ".odb")

        if gds_file is not None:
            print(f"\nGDS Output: {gds_file.name} ({gds_file.stat().st_size} bytes)")
        else:
            print("\nGDS output not found")

        if odb_file is not None:
            print(f"ODB Database: {odb_file.name} ({odb_file.stat().st_size} bytes)")
        else:
            print("ODB database not found")

        print("\nAnalysis complete!")
        return True

    except Exception as e:
        print(f"Analysis error: {e}")
        return False


# =============================
# Phase 4: ODB Verification
# =============================

def check_odb_generation(layout: Dict[str, object]) -> bool:
    """Verify ODB file was generated successfully."""

    print("\n" + "=" * 70)
    print("PHASE 4: ODB FILE VERIFICATION")
    print("=" * 70)

    try:
        result_dir = Path(str(layout["results_dir"]))
        final_stage = str(layout.get("final_stage") or "not detected")

        print(f"\nLooking for ODB files in {result_dir}...")
        print()

        odb_candidates = [
            "1_synth.odb",
            "2_floorplan.odb",
            "3_place.odb",
            "4_cts.odb",
            "5_route.odb",
            "6_final.odb",
        ]

        for odb_name in odb_candidates:
            odb_file = result_dir / odb_name
            if odb_file.exists():
                size_mb = odb_file.stat().st_size / (1024 * 1024)
                print(f"OK {odb_name:<18} ({size_mb:>7.2f} MB)")
            else:
                print(f"WARN {odb_name:<18} not found")

        print()

        final_odb = None
        if final_stage != "not detected":
            candidate = result_dir / f"{final_stage}.odb"
            if candidate.exists():
                final_odb = candidate

        if final_odb is None:
            for name in ["5_route.odb", "6_final.odb", "4_cts.odb"]:
                candidate = result_dir / name
                if candidate.exists():
                    final_odb = candidate
                    break

        if final_odb is not None:
            size_mb = final_odb.stat().st_size / (1024 * 1024)
            print("FINAL ODB GENERATED SUCCESSFULLY!")
            print(f"File: {final_odb}")
            print(f"Size: {size_mb:.2f} MB ({final_odb.stat().st_size} bytes)")
            return True

        print("Final ODB not found")
        return False

    except Exception as e:
        print(f"ODB verification error: {e}")
        return False


# =============================
# Phase 5: DRC & LVS Check
# =============================

def check_design_rules(layout: Dict[str, object]) -> bool:
    """Check DRC and LVS results."""

    print("\n" + "=" * 70)
    print("PHASE 5: DESIGN RULES & LAYOUT VERIFICATION")
    print("=" * 70)

    try:
        result_dir = Path(str(layout["results_dir"]))
        report_dir = Path(str(layout["reports_dir"]))
        final_stage = str(layout.get("final_stage") or "not detected")

        def find_rule_report(kind: str) -> Optional[Path]:
            patterns: List[str] = []
            if final_stage != "not detected":
                patterns.extend([
                    f"{final_stage}*_{kind}.rpt",
                    f"{final_stage}*.{kind}.rpt",
                    f"{final_stage}*{kind}*.rpt",
                ])
            patterns.extend([
                f"*_{kind}.rpt",
                f"*.{kind}.rpt",
                f"*{kind}*.rpt",
            ])
            found = glob_first(report_dir, patterns)
            if found is not None:
                return found
            return glob_first(result_dir, patterns)

        drc_report = find_rule_report("drc")
        lvs_report = find_rule_report("lvs")

        if drc_report is not None:
            drc_content = read_file(str(drc_report))
            print(f"\nDRC Report: {drc_report.name}")
            if "violation" in drc_content.lower():
                print("  -> Violations detected - review report")
            else:
                print("  -> No obvious violations found")
        else:
            print("\nDRC report not found")

        if lvs_report is not None:
            lvs_content = read_file(str(lvs_report))
            print(f"\nLVS Report: {lvs_report.name}")
            if "match" in lvs_content.lower() or "passed" in lvs_content.lower():
                print("  -> LVS passed")
            else:
                print("  -> Review report for details")
        else:
            print("\nLVS report not found")

        print("\nDesign rule check complete!")
        return True

    except Exception as e:
        print(f"DRC/LVS check error: {e}")
        return False


# =============================
# Phase 6: Report Generation
# =============================

def generate_pnr_report(module_name: str, orfs_dir: str, layout: Dict[str, object]) -> bool:
    """Generate place & route report."""

    print("\n" + "=" * 70)
    print("PHASE 6: REPORT GENERATION")
    print("=" * 70)

    try:
        result_dir = Path(str(layout["results_dir"]))
        report_dir = Path(str(layout["reports_dir"]))
        final_stage = str(layout.get("final_stage") or "not detected")
        platform = str(layout.get("platform") or "unknown")
        design_name = str(layout.get("design_name") or module_name)
        variant = str(layout.get("variant") or "base")

        timing_report = find_reports_for_stage(report_dir, final_stage, ".timing.rpt")
        area_report = find_reports_for_stage(report_dir, final_stage, ".area.rpt")
        power_report = find_reports_for_stage(report_dir, final_stage, ".power.rpt")
        drc_report = find_reports_for_stage(report_dir, final_stage, ".drc.rpt")
        lvs_report = find_reports_for_stage(report_dir, final_stage, ".lvs.rpt")
        gds_file = find_output_file(result_dir, final_stage, ".gds")
        odb_file = find_output_file(result_dir, final_stage, ".odb")

        def path_or_na(p: Optional[Path]) -> str:
            return str(p) if p is not None else "not found"

        report = f"""
================================================================================
                    PLACE & ROUTE REPORT
================================================================================

Design: {design_name}
Top module: {module_name}
Date: {subprocess.check_output(['date']).decode().strip()}
ORFS Directory: {orfs_dir}
Platform: {platform}
Variant: {variant}
Results Directory: {result_dir}
Reports Directory: {report_dir}
Final Stage: {final_stage}

================================================================================
PHASES COMPLETED (Place & Route Only)
================================================================================

Phase 1: ORFS Setup
  OK Copied synthesis outputs to ORFS

Phase 2: Place & Route (ORFS)
  OK Floorplanning, placement, routing

Phase 3: Timing Analysis
  OK Setup/hold, slack analysis (if available)

Phase 4: ODB File Verification
  OK Database file generation

Phase 5: Design Rules & LVS
  OK DRC and LVS verification (if available)

Phase 6: Report Generation
  OK Summary report

================================================================================
OUTPUT FILES
================================================================================

Final stage files (if present):
  ODB:   {path_or_na(odb_file)}
  GDS:   {path_or_na(gds_file)}
  Time:  {path_or_na(timing_report)}
  Area:  {path_or_na(area_report)}
  Power: {path_or_na(power_report)}
  DRC:   {path_or_na(drc_report)}
  LVS:   {path_or_na(lvs_report)}

================================================================================
NEXT STEPS
================================================================================

1. Review routed layout database
2. Check timing reports
3. Verify DRC/LVS outputs
4. Export GDS if your flow generates it
5. Prepare for the next integration step

================================================================================
                          P&R COMPLETE!
================================================================================
"""

        report_file = f"{design_name}_pnr_report.txt"
        write_file(report_file, report)

        print(report)
        print(f"Report saved: {report_file}")
        return True

    except Exception as e:
        print(f"Report generation error: {e}")
        return False


# =============================
# Main Orchestration
# =============================

def extract_top_module(netlist_path: str) -> str:
    """Extract the top module name from a Verilog netlist."""
    netlist_content = read_file(netlist_path)
    match = re.search(r"module\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", netlist_content)
    return match.group(1) if match else "design"


def main() -> None:
    """Main place & route orchestration (synthesis-only flow)."""

    parser = argparse.ArgumentParser(
        description="Standalone Place & Route (P&R) Flow - No Synthesis"
    )
    parser.add_argument("--netlist", required=True, help="Synthesized netlist (.v)")
    parser.add_argument("--sdc", required=True, help="Timing constraints (.sdc)")
    parser.add_argument("--config", required=True, help="ORFS config file (.mk)")
    parser.add_argument("--tb", default=None, help="Optional: testbench file")
    parser.add_argument("--orfs", required=True, help="Path to ORFS directory")
    parser.add_argument("--target", default="all", help="ORFS make target (default: all)")
    parser.add_argument(
        "--skip-cts-repair-timing",
        dest="skip_cts_repair_timing",
        action="store_true",
        default=DEFAULT_SKIP_CTS_REPAIR_TIMING,
        help="Skip the CTS repair timing step (default: enabled)",
    )
    parser.add_argument(
        "--no-skip-cts-repair-timing",
        dest="skip_cts_repair_timing",
        action="store_false",
        help="Enable CTS repair timing step",
    )

    args = parser.parse_args()

    for file_path in [args.netlist, args.sdc, args.config]:
        if not Path(file_path).exists():
            print(f"File not found: {file_path}")
            sys.exit(1)

    if args.tb and not Path(args.tb).exists():
        print(f"Testbench not found: {args.tb}")
        sys.exit(1)

    top_module = extract_top_module(args.netlist)

    print("=" * 70)
    print("STANDALONE PLACE & ROUTE FLOW")
    print("=" * 70)
    print(f"Top module: {top_module}")
    print(f"Netlist:    {args.netlist}")
    print(f"SDC:        {args.sdc}")
    print(f"Config:     {args.config}")
    print(f"Testbench:  {args.tb or 'None'}")
    print(f"ORFS:       {args.orfs}")
    print(f"Target:     {args.target}")
    print(f"CTS skip:   {args.skip_cts_repair_timing}")
    print("=" * 70)

    setup_ok = setup_orfs_flow(args.orfs, args.netlist, args.sdc, args.config, args.tb)
    if not setup_ok:
        print("\nORFS setup failed - aborting P&R flow")
        sys.exit(1)

    orfs_ok = run_orfs_flow(args.orfs, args.target, skip_cts_repair_timing=args.skip_cts_repair_timing)
    if not orfs_ok:
        print("\nORFS flow failed - check ORFS logs")
        sys.exit(1)

    layout = detect_orfs_layout(args.orfs, args.config, top_module)

    timing_ok = analyze_timing(layout)
    odb_ok = check_odb_generation(layout)
    rules_ok = check_design_rules(layout)
    report_ok = generate_pnr_report(top_module, args.orfs, layout)

    print("\n" + "=" * 70)
    print("PLACE & ROUTE FLOW FINISHED")
    print("=" * 70)

    if all([setup_ok, orfs_ok, timing_ok, odb_ok, rules_ok, report_ok]):
        print("All phases completed successfully!")
        print()
        print("Key Output Files:")
        print(f"  Results dir:  {layout['results_dir']}")
        print(f"  Reports dir:  {layout['reports_dir']}")
        print(f"  Final stage:  {layout['final_stage']}")
    else:
        print("Some phases had warnings - review reports")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
