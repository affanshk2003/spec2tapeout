#!/usr/bin/env python3
"""
Full 3-Agent Wrapper

Runs the whole flow in one command:
1) Agent 1 -> RTL generation
2) Agent 2 -> Synthesis
3) Agent 3 -> ORFS place & route
4) Optional -> OpenROAD GUI on the final ODB

What this wrapper adds:
- Streams logs live to the terminal
- Auto-detects the top module / design name
- Normalizes ORFS config variables for the selected platform
- Stages the design into the ORFS design tree
- Auto-opens OpenROAD GUI after a successful P&R run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple


# =============================
# Defaults
# =============================

AGENT1_DEFAULT = "agent_v1.5.py"   # RTL generation
AGENT2_DEFAULT = "agent_v2.4.py"   # synthesis
AGENT3_DEFAULT = "agent_v3.3.py"   # ORFS P&R
DEFAULT_ORFS_ROOT = "/OpenROAD-flow-scripts/flow"
DEFAULT_OPENROAD_BIN = "/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad"
DEFAULT_PLATFORM_HINT = "sky130hd"
DEFAULT_SKIP_CTS_REPAIR_TIMING = True


# =============================
# Utilities
# =============================

def run_live(cmd: list[str], cwd: Optional[str] = None, env: Optional[dict] = None) -> int:
    """Run a command and stream stdout/stderr live to the terminal."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        sys.stdout.flush()

    return proc.wait()


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def safe_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def find_latest(folder: Path, suffix: str) -> Optional[Path]:
    if not folder.exists():
        return None
    files = sorted(folder.rglob(f"*{suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def extract_module_name_from_verilog(text: str) -> str:
    match = re.search(r"module\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    return match.group(1) if match else "design"


def parse_makefile_vars(path: Path) -> Dict[str, str]:
    """Parse simple Makefile-style KEY = VALUE assignments."""
    vars_found: Dict[str, str] = {}
    if not path.exists():
        return vars_found

    assign_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:?+]?=\s*(.*?)\s*$")
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
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
        vars_found[key] = value.strip().strip('"').strip("'")
    return vars_found


def guess_platform_from_config(cfg: Dict[str, str], orfs_root: Path) -> str:
    """Map common synthesis-side keys to a real ORFS platform name."""
    platform_hint = (
        cfg.get("PLATFORM")
        or cfg.get("PLATFORM_NAME")
        or cfg.get("PDK")
        or cfg.get("PROCESS")
        or DEFAULT_PLATFORM_HINT
    ).lower()

    # ORFS examples/documentation use platforms such as sky130hd and sky130hs.
    # For sky130 / sky130A flows, sky130hd is the most common ORFS platform name.
    if "sky130" in platform_hint:
        return "sky130hd"
    if "nangate45" in platform_hint or "freepdk45" in platform_hint:
        return "nangate45"
    if "gf180" in platform_hint:
        return "gf180"
    if "asap7" in platform_hint:
        return "asap7"

    # Fall back to a known platform directory if present.
    for candidate in ["sky130hd", "sky130hs", "nangate45", "gf180", "asap7"]:
        if (orfs_root / "platforms" / candidate).exists():
            return candidate

    return DEFAULT_PLATFORM_HINT


def load_or_create_config(
    original_config: Path,
    design_name: str,
    platform: str,
    staged_netlist: Path,
    staged_sdc: Path,
    tb_file: Optional[Path],
    out_dir: Path,
) -> Path:
    """Create an ORFS-friendly config.mk with the right design and platform names."""
    cfg = parse_makefile_vars(original_config)

    # Preserve any extra user settings while fixing the critical ORFS fields.
    lines = original_config.read_text(encoding="utf-8", errors="ignore").splitlines()
    text = "\n".join(lines)

    def replace_or_add(key: str, value: str, source_text: str) -> str:
        pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*[:?+]?=\s*.*$", re.MULTILINE)
        repl = f"export {key} := {value}"
        if pattern.search(source_text):
            return pattern.sub(repl, source_text)
        return source_text.rstrip() + f"\n{repl}\n"

    text = replace_or_add("DESIGN_NAME", design_name, text)
    text = replace_or_add("PLATFORM", platform, text)
    text = replace_or_add("PROCESS", "sky130", text) if "sky130" in platform else text
    text = replace_or_add("PDK", "sky130A", text) if "sky130" in platform else text

    # Point ORFS at the staged files inside the design tree.
    text = replace_or_add("VERILOG_FILES", f"./designs/{platform}/{design_name}/rtl/{staged_netlist.name}", text)
    text = replace_or_add("SDC_FILE", f"./designs/{platform}/{design_name}/constraints/{staged_sdc.name}", text)
    if tb_file is not None:
        text = replace_or_add("TESTBENCH_FILE", f"./designs/{platform}/{design_name}/testbench/{tb_file.name}", text)

    # Create a staging-friendly config with canonical ORFS names.
    out_dir.mkdir(parents=True, exist_ok=True)
    config_out = out_dir / "config.mk"
    safe_write_text(config_out, text + "\n")
    return config_out


def stage_design_into_orfs_tree(
    orfs_root: Path,
    platform: str,
    design_name: str,
    netlist: Path,
    sdc: Path,
    tb_file: Optional[Path] = None,
) -> Tuple[Path, Path, Optional[Path]]:
    """Stage artifacts into ORFS's flow/designs/<platform>/<design>/ structure."""
    design_root = orfs_root / "designs" / platform / design_name
    rtl_dir = design_root / "rtl"
    constraints_dir = design_root / "constraints"
    tb_dir = design_root / "testbench"

    rtl_dir.mkdir(parents=True, exist_ok=True)
    constraints_dir.mkdir(parents=True, exist_ok=True)
    tb_dir.mkdir(parents=True, exist_ok=True)

    staged_netlist = rtl_dir / netlist.name
    staged_sdc = constraints_dir / sdc.name
    shutil.copy2(netlist, staged_netlist)
    shutil.copy2(sdc, staged_sdc)

    staged_tb = None
    if tb_file is not None and tb_file.exists():
        staged_tb = tb_dir / tb_file.name
        shutil.copy2(tb_file, staged_tb)

    return staged_netlist, staged_sdc, staged_tb


def locate_openroad_bin(orfs_root: Path) -> Path:
    """Locate the OpenROAD GUI binary."""
    candidates = [
        orfs_root.parent / "tools" / "install" / "OpenROAD" / "bin" / "openroad",
        orfs_root.parent / "tools" / "OpenROAD" / "bin" / "openroad",
        Path(DEFAULT_OPENROAD_BIN),
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path(DEFAULT_OPENROAD_BIN)


def locate_final_odb(orfs_root: Path, design_name: str) -> Optional[Path]:
    """Find the best final ODB candidate after P&R."""
    results_root = orfs_root / "results"
    candidates = [
        results_root / "sky130hd" / design_name / "base" / "5_route.odb",
        results_root / "sky130hd" / design_name / "base" / "6_final.odb",
        results_root / "nangate45" / design_name / "base" / "5_route.odb",
        results_root / "nangate45" / design_name / "base" / "6_final.odb",
    ]
    for c in candidates:
        if c.exists():
            return c

    # Fallback: any final-ish ODB under results.
    for stage in ["6_final.odb", "5_route.odb", "4_cts.odb"]:
        found = find_latest(results_root, stage)
        if found is not None:
            return found
    return None


def open_gui(orfs_root: Path, odb_file: Path) -> int:
    """Open OpenROAD GUI and load the ODB."""
    openroad_bin = locate_openroad_bin(orfs_root)
    if not openroad_bin.exists():
        print(f"OpenROAD binary not found: {openroad_bin}")
        return 1

    print("\n" + "=" * 70)
    print("OPENROAD GUI")
    print("=" * 70)
    print(f"Binary: {openroad_bin}")
    print(f"ODB:    {odb_file}")

    # Best-effort GUI launch. This keeps the process alive so you can inspect the design.
    proc = subprocess.Popen(
        [str(openroad_bin), "-gui"],
        stdin=subprocess.PIPE,
        stdout=sys.stdout,
        stderr=sys.stderr,
        text=True,
    )

    assert proc.stdin is not None
    commands = [
        f"read_db {odb_file}",
        "gui::show",
    ]
    proc.stdin.write("\n".join(commands) + "\n")
    proc.stdin.flush()

    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 130


# =============================
# Main
# =============================

def main() -> None:
    parser = argparse.ArgumentParser(description="Run RTL -> Synthesis -> ORFS P&R -> optional GUI")

    parser.add_argument("--spec", required=True, help="Spec file for RTL generation")
    parser.add_argument("--tb", required=True, help="Behavioral testbench file")
    parser.add_argument("--cells", required=True, help="Cells directory for synthesis")
    parser.add_argument("--orfs", default=DEFAULT_ORFS_ROOT, help="Path to ORFS flow root")

    parser.add_argument("--agent1", default=AGENT1_DEFAULT, help="RTL generation agent")
    parser.add_argument("--agent2", default=AGENT2_DEFAULT, help="Synthesis agent")
    parser.add_argument("--agent3", default=AGENT3_DEFAULT, help="P&R agent")

    parser.add_argument("--platform", default=None, help="Override ORFS platform (default: auto)")
    parser.add_argument("--open-gui", action="store_true", help="Open OpenROAD GUI after P&R finishes")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary wrapper files")

    args = parser.parse_args()

    spec = Path(args.spec)
    tb = Path(args.tb)
    cells = Path(args.cells)
    orfs_root = Path(args.orfs)
    agent1 = Path(args.agent1)
    agent2 = Path(args.agent2)
    agent3 = Path(args.agent3)

    for p in [spec, tb, cells, orfs_root, agent1, agent2, agent3]:
        if not p.exists():
            print(f"Missing file or directory: {p}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Phase 1: RTL generation
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 1: RTL GENERATION")
    print("=" * 70)
    rc = run_live([
        sys.executable,
        str(agent1),
        "--spec", str(spec),
        "--tb", str(tb),
    ])
    if rc != 0:
        print(f"RTL generation failed with exit code {rc}")
        sys.exit(rc)

    rtl_file = find_latest(Path("rtl"), ".v")
    if rtl_file is None:
        print("Could not find generated RTL in ./rtl")
        sys.exit(1)

    top_module = extract_module_name_from_verilog(safe_read_text(rtl_file))
    print(f"\nRTL: {rtl_file}")
    print(f"Top module: {top_module}")

    # ------------------------------------------------------------------
    # Phase 2: synthesis
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 2: SYNTHESIS")
    print("=" * 70)
    rc = run_live([
        sys.executable,
        str(agent2),
        "--spec", str(spec),
        "--rtl", str(rtl_file),
        "--tb", str(tb),
        "--cells", str(cells),
    ])
    if rc != 0:
        print(f"Synthesis failed with exit code {rc}")
        sys.exit(rc)

    synth_file = find_latest(Path("synthesized"), ".v")
    sdc_file = find_latest(Path("constraints"), ".sdc")
    config_file = find_latest(Path("config"), ".mk")
    postsynth_tb = find_latest(Path("testbench"), "_tb_postsynthesis.v")

    if synth_file is None or sdc_file is None or config_file is None:
        print("Missing synthesis outputs (synthesized netlist / SDC / config.mk)")
        sys.exit(1)

    print(f"\nSynth netlist: {synth_file}")
    print(f"SDC:          {sdc_file}")
    print(f"Config:       {config_file}")
    print(f"Post-TB:      {postsynth_tb if postsynth_tb else 'not generated'}")

    # ------------------------------------------------------------------
    # Normalize config + stage design into ORFS tree
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 3: ORFS PREP")
    print("=" * 70)

    cfg_vars = parse_makefile_vars(config_file)
    platform = args.platform or guess_platform_from_config(cfg_vars, orfs_root)

    staged_netlist, staged_sdc, staged_tb = stage_design_into_orfs_tree(
        orfs_root=orfs_root,
        platform=platform,
        design_name=top_module,
        netlist=synth_file,
        sdc=sdc_file,
        tb_file=postsynth_tb if postsynth_tb else None,
    )

    prep_dir = Path("wrapper_prep") / platform / top_module
    prep_cfg = load_or_create_config(
        original_config=config_file,
        design_name=top_module,
        platform=platform,
        staged_netlist=staged_netlist,
        staged_sdc=staged_sdc,
        tb_file=staged_tb,
        out_dir=prep_dir,
    )

    print(f"Platform:     {platform}")
    print(f"Design root:  {orfs_root / 'designs' / platform / top_module}")
    print(f"Prep config:  {prep_cfg}")

    # ------------------------------------------------------------------
    # Phase 4: ORFS P&R
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 4: ORFS PLACE & ROUTE")
    print("=" * 70)

    pnr_cmd = [
        sys.executable,
        str(agent3),
        "--netlist", str(staged_netlist),
        "--sdc", str(staged_sdc),
        "--config", str(prep_cfg),
        "--orfs", str(orfs_root),
        "--target", "all",
        "--skip-cts-repair-timing",
    ]
    if staged_tb is not None:
        pnr_cmd += ["--tb", str(staged_tb)]

    rc = run_live(pnr_cmd)
    if rc != 0:
        print(f"P&R failed with exit code {rc}")
        sys.exit(rc)

    final_odb = locate_final_odb(orfs_root, top_module)
    print("\n" + "=" * 70)
    print("FLOW COMPLETE")
    print("=" * 70)
    print(f"RTL:       {rtl_file}")
    print(f"SYNTH:     {synth_file}")
    print(f"ORFS:      {orfs_root}")
    print(f"Platform:  {platform}")
    print(f"ODB:       {final_odb if final_odb else 'not found'}")

    # ------------------------------------------------------------------
    # Optional GUI launch
    # ------------------------------------------------------------------
    if args.open_gui:
        if final_odb is None:
            print("\nCannot open GUI: final ODB not found.")
            sys.exit(1)
        rc = open_gui(orfs_root, final_odb)
        sys.exit(rc)

    if not args.keep_temp:
        # Leave wrapper_prep and staged design tree in place, because they are useful
        # for GUI/debug. The flag is here for completeness if you want to clean later.
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
