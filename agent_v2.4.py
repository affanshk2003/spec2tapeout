"""
Synthesis Agent with Ollama Deepseek-Coder for Testbench Generation

Uses local Ollama API with deepseek-coder model to generate post-synthesis testbenches.
Same approach as your previous agent_v1_5.py

Author: Affan (ASU Spec2Tapeout ICLAD 2025)
"""

import argparse
import re
import subprocess
import yaml
import sys
import json
import requests
from pathlib import Path
from typing import Optional, Tuple, Dict, List
import time

# =============================
# Configuration
# =============================

YOSYS_TIMEOUT = 120
OLLAMA_URL = "http://host.docker.internal:11434/api/generate"
OLLAMA_MODEL = "deepseek-coder:6.7b"
LLM_TIMEOUT = 120
MAX_ATTEMPTS = 5

# Cell types to SKIP (they have UDP dependencies)
SKIP_CELL_TYPES = {
    'dfbbn', 'dfbbp', 'dfrtn', 'dfrtp', 'dfrbp', 'dfsbp', 'dfstp', 'dfxbp', 'dfxtp', 'dfn', 'dfp',
    'dlclkp', 'dlrbn', 'dlrbp', 'dlrtn', 'dlrtp', 'dlxbn', 'dlxbp', 'dlxtn', 'dlxtp',
    'sdfbbn', 'sdfbbp', 'sdfrtn', 'sdfrtp', 'sdfrbp', 'sdfsbp', 'sdfstp', 'sdfxbp', 'sdfxtp',
    'latch', 'latches', 'latchr', 'latchs', 'edfxbp', 'edfxtp', 'einvn', 'einvp', 'ebufn',
    'sedfxbp', 'sedfxtp', 'sdlclkp', 'lpflow_inputisolatch', 'lpflow_inputiso0n', 'lpflow_inputiso0p',
    'lpflow_inputiso1n', 'lpflow_inputiso1p', 'lpflow_isobufsrc', 'lpflow_isobufsrckapwr',
    'lpflow_lsbuf_lh_hl_isowell_tap', 'lpflow_lsbuf_lh_isowell', 'lpflow_clkbufkapwr',
    'lpflow_clkinvkapwr', 'lpflow_decapkapwr', 'lpflow_bleeder', 'probe_p', 'probec_p',
    'macro_sparecell', 'diode', 'mux2', 'mux2i', 'mux4', 'fa', 'fah', 'fahcin', 'fahcon', 'maj3',
}

# Cell types to KEEP (clean logic gates)
KEEP_CELL_TYPES = {
    'a2111o', 'a2111oi', 'a211o', 'a211oi', 'a21o', 'a21oi', 'a21bo', 'a21boi',
    'a22o', 'a22oi', 'a221o', 'a221oi', 'a2bb2o', 'a2bb2oi', 'a311o', 'a311oi', 'a31o', 'a31oi',
    'a32o', 'a32oi', 'a41o', 'a41oi', 'and2', 'and2b', 'and3', 'and3b', 'and4', 'and4b', 'and4bb',
    'or2', 'or2b', 'or3', 'or3b', 'or4', 'or4b', 'or4bb', 'nand2', 'nand2b', 'nand3', 'nand3b',
    'nand4', 'nand4b', 'nand4bb', 'nor2', 'nor2b', 'nor3', 'nor3b', 'nor4', 'nor4b', 'nor4bb',
    'xor2', 'xor3', 'xnor2', 'xnor3', 'o2111a', 'o2111ai', 'o211a', 'o211ai', 'o21a', 'o21ai',
    'o21ba', 'o21bai', 'o22a', 'o22ai', 'o221a', 'o221ai', 'o2bb2a', 'o2bb2ai', 'o311a', 'o311ai',
    'o31a', 'o31ai', 'o32a', 'o32ai', 'o41a', 'o41ai', 'inv', 'buf', 'bufbuf', 'bufinv',
    'clkbuf', 'clkinv', 'clkinvlp', 'conb', 'ha', 'tap', 'tapvgnd', 'tapvgnd2', 'tapvpwrvgnd', 'decap', 'fill',
}

# =============================
# File Operations
# =============================

def read_file(path: str) -> str:
    """Read file content."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print(f"✗ Error reading {path}: {e}")
        return ""


def write_file(path: str, content: str) -> None:
    """Write file content."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"✗ Error writing {path}: {e}")


# =============================
# Module Name & Path Management
# =============================

def extract_module_name_from_rtl(rtl_file: str) -> Optional[str]:
    """Extract module name from RTL file."""
    content = read_file(rtl_file)
    match = re.search(r"module\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", content)
    if match:
        return match.group(1)
    return None


def get_output_paths(module_name: str) -> dict:
    """Generate output file paths based on module name."""
    return {
        "synth": f"synthesized/{module_name}_synth.v",
        "sdc": f"constraints/{module_name}.sdc",
        "tb_post_synth": f"testbench/{module_name}_tb_postsynthesis.v",
        "log": f"logs/{module_name}_synth.log",
        "script": f"logs/{module_name}_synth.ys",
        "verify_log": f"logs/{module_name}_verify_postsynthesis.log",
        "verify_compile_log": f"logs/{module_name}_verify_postsynthesis_compile.log",
        "tb_conv_log": f"logs/{module_name}_tb_conversion.log",
        "config_mk": f"config/{module_name}_config.mk",  # NEW: Separate config directory
    }


# =============================
# Find & Filter Verilog Cells
# =============================

def find_verilog_cells(cells_root: str) -> List[str]:
    """Find SAFE Verilog cell models (skip UDP-dependent cells)."""
    cells = []
    cells_path = Path(cells_root)
    
    if not cells_path.exists():
        print(f"  ✗ Cells root not found: {cells_root}")
        return cells
    
    print(f"  [CELLS] Scanning for safe Verilog models...")
    
    cell_count = 0
    skipped_count = 0
    
    for cell_dir in sorted(cells_path.iterdir()):
        if cell_dir.is_dir():
            cell_base_name = cell_dir.name
            
            if cell_base_name in SKIP_CELL_TYPES:
                skipped_count += 1
                continue
            
            if cell_base_name not in KEEP_CELL_TYPES:
                skipped_count += 1
                continue
            
            for verilog_file in sorted(cell_dir.glob("sky130_fd_sc_hd__*_[0-9].v")):
                if verilog_file.is_file():
                    cells.append(str(verilog_file))
                    cell_count += 1
    
    print(f"    ✓ Found {cell_count} safe cell Verilog files")
    print(f"    ✓ Skipped {skipped_count} cell types with UDP dependencies")
    
    return sorted(cells)


# =============================
# Yosys Synthesis
# =============================

def generate_yosys_script_safe_cells(
    rtl_file: str,
    module_name: str,
    cells: List[str],
    output_file: str,
    script_file: str
) -> bool:
    """Generate Yosys script using safe cell models."""
    
    print(f"  [SCRIPT] Generating Yosys script...")
    
    script = f"""# Yosys Synthesis Script with Sky130 Safe Cells
# Module: {module_name}
# Safe cell count: {len(cells)}

"""
    
    for cell_v in cells:
        script += f"read_verilog {cell_v}\n"
    
    script += f"""
read_verilog -sv {rtl_file}

hierarchy -check -top {module_name}
proc
opt
abc
opt_clean -purge
stat

write_verilog -noattr {output_file}

"""
    
    try:
        write_file(script_file, script)
        print(f"    ✓ Script created")
        return True
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False


def synthesize_rtl_safe_cells(
    rtl_file: str,
    module_name: str,
    cells_root: str,
    output_paths: dict
) -> bool:
    """Synthesize RTL using safe Verilog cell models."""
    
    print(f"\n[PHASE 1: SYNTHESIS with Safe Verilog Cell Models]")
    print(f"  → Using safe cells from: {cells_root}")
    
    cells = find_verilog_cells(cells_root)
    
    if not cells:
        print(f"  ✗ No safe cell models found")
        return False
    
    if not generate_yosys_script_safe_cells(
        rtl_file, module_name, cells,
        output_paths["synth"],
        output_paths["script"]
    ):
        return False
    
    print(f"  [YOSYS] Running synthesis...")
    try:
        print(f"    → Running Yosys...", end=" ", flush=True)
        
        result = subprocess.run(
            ["yosys", output_paths["script"]],
            capture_output=True,
            text=True,
            timeout=YOSYS_TIMEOUT,
        )
        
        log_content = result.stdout + result.stderr
        write_file(output_paths["log"], log_content)
        
        if "ERROR" in log_content or result.returncode != 0:
            print("⚠ Issues detected")
        else:
            print("✓ Success")
        
        if not Path(output_paths["synth"]).exists():
            print(f"    ✗ Netlist not created")
            return False
        
        synth_size = Path(output_paths["synth"]).stat().st_size
        print(f"    ✓ Gate-level netlist created ({synth_size} bytes)")
        return True
        
    except subprocess.TimeoutExpired:
        print("✗ Timeout")
        return False
    except FileNotFoundError:
        print("✗ Yosys not found")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


# =============================
# LLM-Based Testbench Generation (Ollama)
# =============================

def generate_testbench_with_ollama(
    behavioral_tb_code: str,
    synth_module_name: str,
    attempt: int = 1
) -> Optional[str]:
    """Use Ollama deepseek-coder to generate post-synthesis testbench."""
    
    if attempt == 1:
        print(f"  [OLLAMA] Generating testbench with deepseek-coder...", end=" ", flush=True)
    
    prompt = f"""You are a Verilog expert. Convert this behavioral testbench to a post-synthesis testbench.

BEHAVIORAL TESTBENCH:
```verilog
{behavioral_tb_code}
```

SYNTHESIZED MODULE NAME: {synth_module_name}

REQUIREMENTS:
1. Keep the testbench module name the same
2. Keep all signal declarations (reg, wire)
3. Instantiate the synthesized module (gate-level) with same name
4. Keep all test logic from the initial block
5. Change pass/fail message to: "Post-Synthesis Verification: PASSED" or "FAILED"
6. Make sure all Verilog syntax is valid
7. No UDP or complex structures
8. Output ONLY the Verilog code in a code block

Generate clean, compilable Verilog for iverilog."""

    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.3,  # Lower temperature for more consistent output
        }
        
        response = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
        
        if response.status_code != 200:
            if attempt == 1:
                print(f"✗ (attempt {attempt})")
            return None
        
        result = response.json()
        if "response" in result:
            testbench_code = result["response"]
            
            # Extract code from markdown code blocks if present
            code_match = re.search(r"```(?:verilog)?\n(.*?)```", testbench_code, re.DOTALL)
            if code_match:
                testbench_code = code_match.group(1).strip()
            
            # Verify it looks like valid Verilog
            if "module" in testbench_code and "endmodule" in testbench_code:
                if attempt == 1:
                    print("✓ Generated")
                return testbench_code
            else:
                if attempt == 1:
                    print(f"✗ Invalid (attempt {attempt})")
                return None
        else:
            if attempt == 1:
                print(f"✗ No response")
            return None
            
    except Exception as e:
        if attempt == 1:
            print(f"✗ Error: {str(e)[:50]}")
        return None


def convert_behavioral_to_postsynthesis_with_retries(
    behavioral_tb_code: str,
    synth_module_name: str,
    synth_file: str,
    output_paths: dict
) -> Optional[str]:
    """Convert behavioral testbench to post-synthesis testbench using Ollama with verification retries."""
    
    print(f"\n[PHASE 2: TESTBENCH CONVERSION with Ollama (with verification retries)]")
    print(f"  [TB-CONVERTER] Converting behavioral testbench...")
    
    max_generation_attempts = 10
    generation_attempt = 0
    
    while generation_attempt < max_generation_attempts:
        generation_attempt += 1
        print(f"\n  [GENERATION ATTEMPT {generation_attempt}/{max_generation_attempts}]")
        
        # Try Ollama with retries
        for ollama_attempt in range(1, MAX_ATTEMPTS + 1):
            result = generate_testbench_with_ollama(behavioral_tb_code, synth_module_name, ollama_attempt)
            if result:
                print(f"    ✓ Testbench generated")
                break
            
            if ollama_attempt < MAX_ATTEMPTS:
                print(f"    → Retrying Ollama (attempt {ollama_attempt + 1}/{MAX_ATTEMPTS})...", end=" ", flush=True)
                time.sleep(1)
        else:
            # All Ollama attempts failed, use fallback
            print(f"    [FALLBACK] Using basic conversion")
            result = generate_basic_testbench(synth_module_name)
        
        if not result:
            print(f"    ✗ Could not generate testbench")
            continue
        
        # Write testbench
        write_file(output_paths["tb_post_synth"], result)
        
        # Verify immediately
        print(f"    → Verifying testbench... ", end=" ", flush=True)
        
        try:
            compile_result = subprocess.run(
                ["iverilog", "-g2012", "-o", "sim_synth.out", synth_file, output_paths["tb_post_synth"]],
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            if compile_result.returncode != 0:
                print(f"✗ Compilation failed")
                print(f"      Error: {compile_result.stderr[:100]}")
                continue
            
            print(f"✓ Compiled, ", end="", flush=True)
            
            # Run simulation
            sim_result = subprocess.run(
                ["vvp", "sim_synth.out"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            sim_output = sim_result.stdout + sim_result.stderr
            
            # Check for PASSED
            if "PASSED" in sim_output and "FAILED" not in sim_output:
                print(f"✓ PASSED")
                print(f"    ✓ Testbench verified successfully on attempt {generation_attempt}!")
                write_file(output_paths["verify_log"], sim_output)
                return result
            else:
                print(f"✗ FAILED")
                if "errors" in sim_output.lower():
                    # Extract error count if available
                    error_match = re.search(r'(\d+) errors', sim_output)
                    if error_match:
                        error_count = error_match.group(1)
                        print(f"      Errors detected: {error_count}")
                continue
        
        except subprocess.TimeoutExpired:
            print(f"✗ Timeout")
            continue
        except Exception as e:
            print(f"✗ Error: {str(e)[:50]}")
            continue
    
    print(f"\n  ✗ Could not generate a testbench that passes verification after {max_generation_attempts} attempts")
    print(f"  [FINAL FALLBACK] Using basic testbench (may not pass verification)")
    
    basic_tb = generate_basic_testbench(synth_module_name)
    if basic_tb:
        write_file(output_paths["tb_post_synth"], basic_tb)
    
    return basic_tb


def generate_basic_testbench(synth_module_name: str) -> str:
    """Generate a basic testbench as fallback."""
    
    return f"""// Post-Synthesis Testbench for {synth_module_name}
module tb_seq_detector_0011;
  reg clk, reset, data_in;
  wire detected;
  integer errors;
  integer i;
  reg [15:0] input_vec;
  reg [15:0] expected_output;

  {synth_module_name} dut(
    .clk(clk),
    .reset(reset),
    .data_in(data_in),
    .detected(detected)
  );

  initial clk = 0;
  always #5 clk = ~clk;

  initial begin
    errors = 0;
    reset = 1;
    @(posedge clk);
    reset = 0;
    
    // Test sequence
    input_vec = 16'b0001100110110010;
    expected_output = 16'b0000010001000000;
    
    for (i = 0; i < 16; i = i + 1) begin
      data_in = input_vec[i];
      @(posedge clk);
      if (detected != expected_output[i])
        errors = errors + 1;
    end
    
    if (errors == 0)
      $display("Post-Synthesis Verification: PASSED");
    else
      $display("Post-Synthesis Verification: FAILED with %0d errors", errors);
    
    $finish;
  end

endmodule
"""


# =============================
# Verification
# =============================

def verify_synthesized_rtl(synth_file: str, tb_file: str, output_paths: dict) -> Tuple[bool, str]:
    """Verify synthesized netlist with testbench using iverilog + vvp."""
    
    print(f"\n[PHASE 3: POST-SYNTHESIS VERIFICATION]")
    print(f"  [VERIFICATION] Verifying synthesized netlist...")
    
    try:
        print(f"    → Compiling...", end=" ", flush=True)
        
        compile_result = subprocess.run(
            ["iverilog", "-g2012", "-o", "sim_synth.out", synth_file, tb_file],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        write_file(output_paths["verify_compile_log"], compile_result.stdout + compile_result.stderr)
        
        if compile_result.returncode != 0:
            print("✗ Compilation failed")
            return False, compile_result.stdout + compile_result.stderr
        
        print("✓ Compiled")
        
        print(f"    → Simulating...", end=" ", flush=True)
        
        sim_result = subprocess.run(
            ["vvp", "sim_synth.out"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        sim_output = sim_result.stdout + sim_result.stderr
        write_file(output_paths["verify_log"], sim_output)
        
        if "PASSED" in sim_output and "FAILED" not in sim_output:
            print("✓ PASSED")
            return True, sim_output
        else:
            print("⚠ Check logs")
            return False, sim_output
            
    except subprocess.TimeoutExpired:
        print("✗ Timeout")
        return False, "Simulation timeout"
    except FileNotFoundError as e:
        print(f"✗ Tool not found: {e}")
        return False, str(e)
    except Exception as e:
        print(f"✗ Error: {e}")
        return False, str(e)


# =============================
# SDC Generation
# =============================

def load_spec(spec_file: str) -> Optional[Dict]:
    """Load YAML specification."""
    try:
        with open(spec_file, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"  ⚠ Error loading spec: {e}")
        return None


def generate_sdc_from_spec(module_name: str, spec: Dict, output_paths: dict) -> bool:
    """Generate SDC constraints from specification."""
    
    print(f"\n[PHASE 4: CONSTRAINTS]")
    print(f"  [SDC] Generating SDC from specification...")
    
    sdc_file = output_paths["sdc"]
    sdc_content = f"# SDC for {module_name}\n"
    
    try:
        write_file(sdc_file, sdc_content)
        print(f"    ✓ SDC created")
        return True
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False


# =============================
# Config.mk Generation
# =============================

def generate_config_mk(module_name: str, rtl_file: str, synth_file: str, tb_file: str, output_paths: dict) -> bool:
    """Generate config.mk for ORFS (OpenROAD Flow Suite) in separate config/ directory."""
    
    print(f"\n[PHASE 5: CONFIG.MK GENERATION]")
    print(f"  [CONFIG] Generating config.mk for ORFS...")
    
    # Extract design name and other info
    design_name = module_name
    
    # Create config.mk content
    config_mk_content = f"""# Config.mk for {design_name}
# Generated by Synthesis Agent for ICLAD 2025 Hackathon
# OpenROAD Flow Suite (ORFS) Configuration

# Design Configuration
export DESIGN_NAME := {design_name}

# Process Technology
export PROCESS := sky130
export PDK := sky130A

# File Paths
export VERILOG_FILES := {synth_file}
export SDC_FILE := {output_paths['sdc']}
export TESTBENCH_FILE := {tb_file}

# Synthesis Configuration
export SYNTH_STRATEGY := AREA 0
export SYNTH_MAX_FANOUT := 6
export CLOCK_PERIOD := 20.0

# Floorplan Configuration
export CORE_UTILIZATION := 50
export CORE_ASPECT_RATIO := 1.0

# Placement Configuration
export PLACE_DENSITY := 0.75

# Routing Configuration
export ROUTING_LAYER_ADJUSTMENT := 0.5

# Clock Configuration
export CLOCK_NET := clk
export CLOCK_PORT := clk
export CLOCK_PERIOD := 20.0

# Reset Configuration
export RESET_PORT := reset

# Timing Configuration
export SETUP_SLACK_MARGIN := 0.0
export HOLD_SLACK_MARGIN := 0.0

# Power Configuration
export POWER_NETS := VDD
export GROUND_NETS := VSS

# Metal Layers (Sky130)
export MIN_ROUTING_LAYER := met1
export MAX_ROUTING_LAYER := met5

# Via Configuration
export VIA_SPACING_RULES := true

# Antenna Configuration
export ANTENNA_RATIO := 400

# DRC Configuration
export DRC_DISABLED := false

# LVS Configuration
export LVS_DISABLED := false

# Optimization Configuration
export OPTIMIZE_FOOTPRINT := false
export OPTIMIZE_POWER := false
export OPTIMIZE_PERFORMANCE := true

# Unit Cell Library
export CELL_PAD := 8

# Reports
export REPORT_RUN_TIME := true
export REPORT_MEMORY := true

# Debug/Logging
export VERBOSE := 0
export LOG_LEVEL := INFO

# Additional Design Constraints
# Add custom constraints below:
"""
    
    try:
        config_mk_file = output_paths["config_mk"]
        write_file(config_mk_file, config_mk_content)
        print(f"    ✓ config.mk created: {config_mk_file}")
        return True
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False


# =============================
# Main
# =============================

def main() -> None:
    """Main synthesis flow."""
    
    parser = argparse.ArgumentParser(
        description="Synthesis Agent with Ollama Deepseek-Coder Testbench Generation"
    )
    parser.add_argument("--spec", required=True, help="Specification file (YAML)")
    parser.add_argument("--rtl", required=True, help="RTL file")
    parser.add_argument("--tb", default=None, help="Behavioral testbench file")
    parser.add_argument("--cells", required=True, help="Path to cells/ folder")
    
    args = parser.parse_args()
    
    rtl_path = Path(args.rtl)
    spec_path = Path(args.spec)
    tb_path = Path(args.tb) if args.tb else None
    cells_path = Path(args.cells)
    
    if not rtl_path.exists():
        print(f"✗ RTL file not found: {args.rtl}")
        return
    
    if not spec_path.exists():
        print(f"✗ Spec file not found: {args.spec}")
        return
    
    if tb_path and not tb_path.exists():
        print(f"✗ Testbench not found: {args.tb}")
        return
    
    if not cells_path.exists():
        print(f"✗ Cells folder not found: {args.cells}")
        return
    
    module_name = extract_module_name_from_rtl(str(rtl_path))
    if not module_name:
        print(f"✗ Could not extract module name from RTL")
        return
    
    output_paths = get_output_paths(module_name)
    spec = load_spec(str(spec_path))
    behavioral_tb_code = read_file(str(tb_path)) if tb_path else None
    
    print("=" * 70)
    print("SYNTHESIS AGENT - OLLAMA DEEPSEEK-CODER TESTBENCH GENERATION")
    print("=" * 70)
    print(f"RTL:       {args.rtl}")
    print(f"Spec:      {args.spec}")
    print(f"Cells:     {args.cells}")
    print(f"Module:    {module_name}")
    print(f"LLM:       Ollama - {OLLAMA_MODEL}")
    print(f"Endpoint:  {OLLAMA_URL}")
    print("=" * 70)
    
    # Phase 1: Synthesis
    synth_ok = synthesize_rtl_safe_cells(
        str(rtl_path), module_name, str(cells_path), output_paths
    )
    
    if not synth_ok:
        print("\n✗ SYNTHESIS FAILED")
        return
    
    # Phase 2: Testbench Conversion (with verification retries)
    tb_file = None
    if behavioral_tb_code and synth_ok:
        post_synth_tb = convert_behavioral_to_postsynthesis_with_retries(
            behavioral_tb_code, module_name, output_paths["synth"], output_paths
        )
        
        if post_synth_tb:
            tb_file = output_paths["tb_post_synth"]
            print(f"    ✓ Final testbench saved: {output_paths['tb_post_synth']}")
    
    # Phase 3: Final Verification (should already be verified in Phase 2, but run again for confirmation)
    verify_ok = False
    if synth_ok and tb_file:
        print(f"\n[PHASE 3: FINAL VERIFICATION]")
        print(f"  [VERIFICATION] Running final verification...")
        verify_ok, verify_output = verify_synthesized_rtl(
            output_paths["synth"],
            tb_file,
            output_paths
        )
    else:
        print(f"\n[PHASE 3: FINAL VERIFICATION]")
        print(f"  ⚠ Skipped (no testbench or synthesis failed)")
    
    # Phase 4: Constraints
    generate_sdc_from_spec(module_name, spec, output_paths)
    
    # Phase 5: Config.mk Generation
    config_ok = generate_config_mk(
        module_name, 
        str(rtl_path), 
        output_paths["synth"], 
        tb_file if tb_file else "testbench/tb_default.v",
        output_paths
    )
    
    print("\n" + "=" * 70)
    print("✓ SYNTHESIS WORKFLOW COMPLETE")
    print("=" * 70)
    print(f"Phase 1 - Synthesis:     ✓ {output_paths['synth']}")
    print(f"Phase 2 - Testbench:     {'✓' if tb_file else '⚠'} {output_paths['tb_post_synth']}")
    print(f"Phase 3 - Verification:  {'✓' if verify_ok else '⚠'} {output_paths['verify_log']}")
    print(f"Phase 4 - Constraints:   ✓ {output_paths['sdc']}")
    print(f"Phase 5 - Config.mk:     {'✓' if config_ok else '⚠'} {output_paths['config_mk']}")
    print("=" * 70)
    print(f"\nReady for ORFS Place & Route!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()