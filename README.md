# Spec2Tapeout — AI Agent Pipeline for RTL-to-GDS Automation

> **EEE 598 — VLSI Design Automation | Mini Project 2 | Phase 3**  
> Affan Akram Shaikh • Jamaluddin Arfi | Arizona State University | Spring 2026

An autonomous AI agent pipeline that transforms a YAML hardware specification into a
manufacturable GDSII layout — **zero manual steps, single command**.

---

## Results Summary (Phase 3)

| Problem | Design | Spec Clock | WNS | Area | GDS | Status |
|---------|--------|-----------|-----|------|-----|--------|
| p1 | seq_detector_0011 | 1.1 ns | +1.76 ns | 188 µm² | 77 KB | ✅ Complete (6/6 stages) |
| p5 | dot_product (N=8) | 4.5 ns | ~+0.8 ns | ~900 µm² | ✅ | ✅ Complete (6/6 stages) |
| p7 | exp_fixed_point | 4.5 ns | ~+1.0 ns | ~350 µm² | ✅ | ✅ Complete (6/6 stages) |
| p8 | fp16_multiplier | 9.0 ns | — | — | — | ❌ RTL gen failed (SLM limit) |
| p9 | fir_filter (N=8) | 8.0 ns | — | — | — | ❌ RTL gen failed (SLM limit) |

> p8/p9 failures are due to the capacity ceiling of deepseek-coder:6.7b running locally.
> IEEE 754 FP and parametric FIR with `$clog2` port widths exceed the 6.7b model's
> reliable generation range. A 33b+ model would resolve both.

---

## What's New in Phase 3

All 7 Phase 2 bugs are fixed:

| Phase 2 Bug | Phase 3 Fix |
|-------------|-------------|
| Silent GCD fallback in ORFS | ORFS given RTL directly; absolute staged paths; DESIGN_CONFIG env+make var |
| `$_DFF_`/`$adff` unmapped primitives | ORFS runs its own synthesis from RTL; our Yosys is verification-only |
| Blind retry (no error feedback) | iverilog stderr injected into next generation prompt |
| SDC stub — no clock constraint | Full SDC: create_clock, I/O delays, false paths, clock margin scaling |
| CTS repair_timing SIGILL crash | `SKIP_CTS_REPAIR_TIMING=1` + `CTS_ARGS=-sink_clustering_enable` |
| All metrics N/A (GUI crash) | Headless OpenROAD batch: `estimate_parasitics` + `report_wns/tns/power/area` |
| SV testbench fails `-g2005` | Auto-detect TB standard; compile `-g2012` for SV, `-g2005` for Verilog |

---

## Repository Structure

```
spec2tapeout/
├── agent.py                    ← Single entry point — runs the full flow
├── run_rtl2gds.bat             ← Windows launcher (double-click to run)
│
├── problems/                   ← Design specifications (YAML)
│   ├── p1.yaml                 seq_detector_0011
│   ├── p5.yaml                 dot_product
│   ├── p7.yaml                 exp_fixed_point
│   ├── p8.yaml                 fp16_multiplier
│   └── p9.yaml                 fir_filter
│
├── testbench/                  ← Behavioral testbenches
│   ├── p1.v
│   ├── p5.v
│   ├── p7.v
│   ├── p8.v
│   └── p9.v
│
├── example_outputs/            ← Example outputs from a successful run
│   └── seq_detector_0011/
│       ├── gds/                6_final.gds (77 KB)
│       ├── odb/                Stage ODBs 1–6
│       ├── reports/            Timing, area, power, ORFS logs
│       ├── rtl/                Generated RTL + synthesized netlist
│       └── constraints/        SDC file
│
└── README.md
```

> **Sky130HD cells** are not included (repo size limit).
> Clone separately: `git clone https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd`
> Place at `skywater-pdk-libs-sky130_fd_sc_hd/` in your project folder.

---

## Pipeline Architecture

```
YAML Spec + Testbench + Sky130HD cells
              │
              ▼
┌─────────────────────────────┐
│  Phase 1 — RTL Generation   │  deepseek-coder:6.7b (Ollama)
│  generate → compile → sim   │  error-guided retry, up to 50×
│  SV-aware prompt + sig inj  │  auto-detect TB standard (-g2012/-g2005)
└─────────────┬───────────────┘
              │  Verified RTL (.v)
              ▼
┌─────────────────────────────┐
│  Phase 2 — Synthesis        │  Yosys + sky130 .lib
│  read_liberty → dfflibmap   │  SDC from YAML clock_period
│  → abc -liberty             │  config.mk with absolute paths
└─────────────┬───────────────┘
              │  RTL → ORFS (not pre-mapped netlist)
              ▼
┌─────────────────────────────┐
│  Phase 3 — Place & Route    │  OpenROAD ORFS make finish
│  6 stages: synth → floor    │  CTS SIGILL bypass
│  → place → CTS → route      │  headless batch metrics
│  → final                    │  GDS + reports → /workspace
└─────────────────────────────┘
              │
              ▼
  /workspace/results/<module>/
    gds/    odb/    reports/    rtl/    constraints/
```

---

## Environment Setup

### Prerequisites

| Tool | Runs On | Install |
|------|---------|---------|
| Docker Desktop | Windows host | https://www.docker.com/products/docker-desktop |
| Ollama | Windows host | https://ollama.ai |
| deepseek-coder:6.7b | Windows host | `ollama pull deepseek-coder:6.7b` |
| VcXsrv (optional GUI) | Windows host | https://sourceforge.net/projects/vcxsrv |
| openroad/orfs image | Docker | `docker pull openroad/orfs` |
| Sky130HD cells | Project folder | `git clone https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd` |

### 1 — Start Ollama on Windows host

```powershell
# In a dedicated PowerShell window — keep this running
set OLLAMA_HOST=0.0.0.0:11434
ollama serve
```

### 2 — Pull the model (one-time)

```powershell
ollama pull deepseek-coder:6.7b
```

### 3 — Verify connectivity from Docker

```bash
curl http://host.docker.internal:11434/api/tags
# Should return JSON with deepseek-coder:6.7b listed
```

---

## Running the Pipeline

### Option A — Windows batch file (easiest)

Double-click `run_rtl2gds.bat` in File Explorer, or from PowerShell:

```powershell
.\run_rtl2gds.bat p1    # runs seq_detector_0011
.\run_rtl2gds.bat p5    # runs dot_product
.\run_rtl2gds.bat p7    # runs exp_fixed_point
```

### Option B — Manual Docker command

```powershell
"C:\Program Files\Docker\Docker\resources\bin\docker.exe" run -it `
  -e DISPLAY=host.docker.internal:0.0 `
  -v "C:\path\to\your\project":/workspace `
  openroad/orfs `
  bash -c "cd /workspace && python3 agent.py --spec problems/p1.yaml --tb testbench/p1.v --cells skywater-pdk-libs-sky130_fd_sc_hd/cells --orfs /OpenROAD-flow-scripts/flow"
```

### Option C — Inside the container directly

```bash
# Start container
docker run -it -e DISPLAY=host.docker.internal:0.0 \
  -v "$(pwd)":/workspace openroad/orfs

# Inside container
cd /workspace
python3 agent.py \
  --spec problems/p1.yaml \
  --tb testbench/p1.v \
  --cells skywater-pdk-libs-sky130_fd_sc_hd/cells \
  --orfs /OpenROAD-flow-scripts/flow
```

### CLI arguments

```
python3 agent.py
  --spec    problems/p1.yaml          # YAML specification (required)
  --tb      testbench/p1.v            # Behavioral testbench (required)
  --cells   skywater-.../cells        # Sky130HD cells directory (required)
  --orfs    /OpenROAD-flow-scripts/flow  # ORFS root (required for P&R)

  --stop-after  rtl                   # Stop after RTL generation only
  --stop-after  synth                 # Stop after synthesis (skip P&R)
  --max-rtl     50                    # Max RTL generation attempts (default: 50)
  --platform    sky130hd              # ORFS platform (default: sky130hd)
  --target      finish                # ORFS make target (default: finish)
  --model       deepseek-coder:6.7b   # Ollama model (default: deepseek-coder:6.7b)
```

---

## Input / Output Description

### Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Design specification | YAML | Module name, ports, behavior, clock period, tech node |
| Behavioral testbench | Verilog or SystemVerilog | Prints PASS/FAIL on stdout |
| Sky130HD cells | Directory of `.v` files | `skywater-pdk-libs-sky130_fd_sc_hd/cells/` |

### Outputs (all saved to `/workspace/results/<module>/`)

```
results/<module>/
├── gds/
│   └── 6_final.gds              ← Tapeout file
├── odb/
│   ├── 1_synth.odb
│   ├── 2_floorplan.odb
│   ├── 3_place.odb
│   ├── 4_cts.odb
│   ├── 5_route.odb
│   └── 6_final.odb              ← Open in OpenROAD GUI
├── reports/
│   ├── <module>_pnr_report.txt  ← WNS, TNS, area, power, DRC
│   ├── logs/                    ← All ORFS stage logs
│   └── *.rpt                    ← Timing/area/power reports
├── rtl/
│   ├── <module>.v               ← Verified RTL
│   └── <module>_synth.v         ← Gate-level netlist
└── constraints/
    └── <module>.sdc             ← SDC timing constraints
```

---

## Expected Results

### p1 — seq_detector_0011 (verified)

```
════════════════════════════════════════════════════
  RTL-to-GDS COMPLETE REPORT — seq_detector_0011
════════════════════════════════════════════════════
  WNS         : +1.760 ns   ✓ TIMING MET
  TNS         : 0.000 ns
  Design area : 188 µm²
  Utilization : 17%
  GDS         : 6_final.gds (77 KB)
  ORFS stages : 6/6 complete
════════════════════════════════════════════════════
```

Typical runtimes:
- Phase 1 RTL generation: 2–8 minutes (8–30 LLM attempts)
- Phase 2 Synthesis: ~30 seconds
- Phase 3 P&R: ~3–5 minutes

---

## How to Run Hidden Testcases

The grader can reproduce results on any hidden testcase by following these steps:

**1.** Place the spec file in `problems/<name>.yaml`

**2.** Place the testbench in `testbench/<name>.v`

**3.** Run:

```bash
python3 agent.py \
  --spec problems/<name>.yaml \
  --tb   testbench/<name>.v \
  --cells skywater-pdk-libs-sky130_fd_sc_hd/cells \
  --orfs  /OpenROAD-flow-scripts/flow
```

**Requirements for any testcase:**
- YAML root key = module name (e.g. `seq_detector_0011:`)
- Testbench prints `PASS` (exactly) on success
- Design is synthesisable on Sky130HD
- `clock_period` field present in YAML

The pipeline auto-detects the module name, TB language standard (Verilog-2005 vs SystemVerilog),
and applies appropriate clock margin scaling automatically.

---

## Viewing the Layout

### With X11 (VcXsrv running on Windows host)

```bash
# Inside ORFS container
DISPLAY=host.docker.internal:0.0 \
/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad -gui \
-script /OpenROAD-flow-scripts/flow/results/sky130hd/seq_detector_0011/base/gui_init.tcl
```

### Without display (headless batch)

```bash
/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad -no_gui << 'TCL'
read_db /OpenROAD-flow-scripts/flow/results/sky130hd/seq_detector_0011/base/6_final.odb
report_design_area
report_wns
report_tns
report_power
TCL
```

### KLayout (on Windows, install separately)

```
klayout results\seq_detector_0011\gds\6_final.gds
```

---

## Known Limitations

| Limitation | Details |
|------------|---------|
| SLM capacity (p8, p9) | deepseek-coder:6.7b cannot reliably generate IEEE 754 FP logic or parametric FIR with `$clog2` port widths. Fix: use 33b+ model. |
| CTS SIGILL bypass | `SKIP_CTS_REPAIR_TIMING=1` is required for OpenROAD build 26Q1-2290. Safe for these designs (timing closes at placement). |
| No gate-level timing sim | Only pre-P&R functional verification. SDF-annotated sim not implemented. |
| Sequential execution | All problems run one at a time. Parallel Docker instances would reduce total runtime. |

---

## Phase History

| Phase | Entry Point | Status |
|-------|-------------|--------|
| Phase 1 | `agent_v1_5.py` | ✅ Archived |
| Phase 2 | `pipeline.py` (orchestrates v1/v2/v3) | ✅ Archived |
| Phase 3 | `agent.py` (unified, 2,700 lines) | ✅ Current |

---

## Acknowledgements

- SkyWater 130HD PDK: Google / SkyWater Technology Foundry
- OpenROAD / ORFS: The OpenROAD Project — https://github.com/The-OpenROAD-Project
- DeepSeek-Coder: DeepSeek AI — https://github.com/deepseek-ai/DeepSeek-Coder
- Ollama: https://ollama.ai
- ICLAD 2025 Hackathon: https://iclad.ai
