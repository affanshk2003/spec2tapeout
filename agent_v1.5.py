"""
Clean RTL Generation & Verification Agent

Simple workflow:
1. Extract module name from first line of spec
2. Generate RTL from spec
3. Verify with testbench
4. If failed, generate again
5. Repeat until success or max attempts

Output files are named based on module name to avoid overwrites
"""

import argparse
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

import requests

# =============================
# Configuration
# =============================

MODEL_NAME = "deepseek-coder:6.7b"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_URL = "http://host.docker.internal:11434/api/generate"

MAX_ATTEMPTS = 50
LLM_TIMEOUT = 120

# =============================
# File Operations
# =============================

def read_file(path: str) -> str:
    """Read file content."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    """Write file content."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# =============================
# Dynamic File Paths
# =============================

def get_output_paths(module_name: str, custom_rtl_out: Optional[str] = None) -> dict:
    """Generate output file paths based on module name."""
    if custom_rtl_out:
        rtl_file = custom_rtl_out
    else:
        rtl_file = f"rtl/{module_name}.v"
    
    sim_log = f"logs/{module_name}_sim.log"
    debug_log = f"logs/{module_name}_debug.log"
    
    return {
        "rtl": rtl_file,
        "sim": sim_log,
        "debug": debug_log,
    }


# =============================
# Text Processing
# =============================

def sanitize_text(text: str) -> str:
    """Clean text."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "").replace("\u200b", "")
    return text.strip()


def extract_verilog_code(text: str) -> Optional[str]:
    """Extract Verilog code from LLM response."""
    if not text:
        return None
    
    text = sanitize_text(text)
    
    # Strategy 1: Fenced code block
    match = re.search(r"```(?:verilog|v)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if match:
        code = match.group(1).strip()
        if "module" in code.lower() and "endmodule" in code.lower():
            return code
    
    # Strategy 2: Flexible fenced block
    match = re.search(r"```(?:verilog|v)?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        code = match.group(1).strip()
        if "module" in code.lower() and "endmodule" in code.lower():
            return code
    
    # Strategy 3: Direct module to endmodule
    match = re.search(r"(module\s+.*?endmodule)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    return None


def clean_verilog(code: str) -> str:
    """Clean and validate Verilog code."""
    if not code:
        return ""
    
    code = sanitize_text(code)
    
    # Trim after endmodule
    match = re.search(r"(?is)\bendmodule\b", code)
    if match:
        code = code[:match.end()]
    
    # Remove non-ASCII
    code = code.encode("ascii", errors="ignore").decode("ascii")
    
    # Clean up whitespace
    lines = [line.rstrip() for line in code.split("\n")]
    cleaned = []
    prev_blank = False
    
    for line in lines:
        if line.strip():
            cleaned.append(line)
            prev_blank = False
        elif not prev_blank:
            cleaned.append("")
            prev_blank = True
    
    code = "\n".join(cleaned).strip()
    return code + "\n" if code else ""


# =============================
# Module Name Extraction
# =============================

def extract_module_name_from_spec(spec_text: str) -> str:
    """Extract module name from first line of spec."""
    if not spec_text:
        return "design"
    
    # Get first non-empty line
    lines = spec_text.strip().split("\n")
    first_line = lines[0].strip() if lines else ""
    
    if not first_line:
        return "design"
    
    # Pattern 1: "MODULE: module_name" or "module: module_name"
    match = re.search(r"(?i)module\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", first_line)
    if match:
        return match.group(1)
    
    # Pattern 2: Just the module name (e.g., "seq_detector_0011")
    match = re.search(r"^([A-Za-z_][A-Za-z0-9_]*)", first_line)
    if match:
        potential_name = match.group(1)
        # Validate it's not a common word
        if potential_name.lower() not in ["module", "design", "rtl", "verilog"]:
            return potential_name
    
    return "design"


# =============================
# LLM Interface
# =============================

def call_llm(prompt: str, temperature: float = 0.15, timeout: int = LLM_TIMEOUT) -> Optional[str]:
    """Call Ollama LLM."""
    try:
        print(f"  [LLM] Calling model (timeout={timeout}s)...", end=" ", flush=True)
        
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=timeout,
        )
        
        response.raise_for_status()
        result = response.json().get("response", "")
        
        if result:
            print("✓ Got response")
            return result
        else:
            print("✗ Empty response")
            return None
            
    except requests.exceptions.Timeout:
        print("✗ Timeout")
        return None
    except Exception as e:
        print(f"✗ Error: {e}")
        return None


def generate_rtl(spec: str, module_name: str, attempt: int) -> Optional[str]:
    """Generate RTL from specification."""
    print(f"\n[GEN {attempt}] Generating RTL from spec...")
    
    prompt = f"""Generate Verilog RTL for the following specification:

MODULE NAME: {module_name}

SPECIFICATION:
{spec}

Requirements:
- Generate ONLY valid Verilog code
- Start with module {module_name}(...)
- End with endmodule
- Include all necessary inputs/outputs
- Implement the exact behavior specified
- Use proper Verilog syntax
- Output the code in a ```verilog code block

Generate the Verilog code:"""

    response = call_llm(prompt, temperature=0.15)
    
    if not response:
        print("  ✗ LLM failed to generate")
        return None
    
    # Extract code
    code = extract_verilog_code(response)
    if not code:
        print("  ✗ Could not extract Verilog from response")
        return None
    
    # Clean code
    code = clean_verilog(code)
    if not code:
        print("  ✗ Code cleaning failed")
        return None
    
    # Validate module name
    if f"module {module_name}" not in code.lower():
        print(f"  ✗ Module name '{module_name}' not found in generated code")
        return None
    
    print(f"  ✓ Generated RTL ({len(code)} chars)")
    return code


# =============================
# Verification
# =============================

def verify_rtl(rtl_file: str, tb_file: str, sim_log: str) -> Tuple[bool, str]:
    """Verify RTL with testbench."""
    print(f"  [VERIFY] Running verification...", end=" ", flush=True)
    
    # Compile
    try:
        compile_result = subprocess.run(
            ["iverilog", "-g2012", "-o", "sim.out", rtl_file, tb_file],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if compile_result.returncode != 0:
            error_msg = compile_result.stdout + compile_result.stderr
            print(f"✗ Compilation failed")
            return False, error_msg
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False, str(e)
    
    # Simulate
    try:
        sim_result = subprocess.run(
            ["vvp", "sim.out"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        
        sim_output = sim_result.stdout + sim_result.stderr
        write_file(sim_log, sim_output)
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False, str(e)
    
    # Check result
    if "PASS" in sim_output and "FAIL" not in sim_output:
        print("✓ PASSED")
        return True, ""
    else:
        print("✗ FAILED")
        return False, sim_output


# =============================
# Main Loop
# =============================

def main() -> None:
    """Main generation + verification loop."""
    parser = argparse.ArgumentParser(
        description="RTL Generation & Verification Agent"
    )
    parser.add_argument("--spec", required=True, help="Specification file (YAML or text)")
    parser.add_argument("--tb", required=True, help="Testbench file (Verilog)")
    parser.add_argument("--rtl-out", default=None, help="Custom output RTL file (optional)")
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS, help="Max generation attempts")
    parser.add_argument("--model", default=MODEL_NAME, help="LLM model name")
    
    args = parser.parse_args()
    
    # Validate files
    spec_path = Path(args.spec)
    tb_path = Path(args.tb)
    
    if not spec_path.exists():
        print(f"✗ Spec file not found: {args.spec}")
        return
    
    if not tb_path.exists():
        print(f"✗ Testbench file not found: {args.tb}")
        return
    
    # Load files
    spec_text = read_file(str(spec_path))
    tb_text = read_file(str(tb_path))
    
    # Extract module name from first line of spec
    module_name = extract_module_name_from_spec(spec_text)
    
    # Get dynamic output paths based on module name
    output_paths = get_output_paths(module_name, args.rtl_out)
    rtl_file = output_paths["rtl"]
    sim_log = output_paths["sim"]
    debug_log = output_paths["debug"]
    
    print("=" * 70)
    print("RTL GENERATION & VERIFICATION AGENT")
    print("=" * 70)
    print(f"Spec file: {args.spec}")
    print(f"Testbench: {args.tb}")
    print(f"Module: {module_name}")
    print(f"Output RTL: {rtl_file}")
    print(f"Output SIM LOG: {sim_log}")
    print(f"Output DEBUG LOG: {debug_log}")
    print(f"Max attempts: {args.max_attempts}")
    print("=" * 70)
    
    # Generation + Verification Loop
    rtl_code = None
    
    for attempt in range(1, args.max_attempts + 1):
        # Generate
        rtl_code = generate_rtl(spec_text, module_name, attempt)
        
        if not rtl_code:
            if attempt < args.max_attempts:
                print(f"  Retrying... ({attempt}/{args.max_attempts})")
                continue
            else:
                print("\n✗ FAILED: Could not generate valid RTL")
                return
        
        # Save generated RTL
        write_file(rtl_file, rtl_code)
        
        # Verify
        passed, error_msg = verify_rtl(rtl_file, str(tb_path), sim_log)
        
        if passed:
            print("\n" + "=" * 70)
            print("✓ SUCCESS! RTL verification passed!")
            print("=" * 70)
            print(f"RTL saved to: {rtl_file}")
            print(f"Simulation log: {sim_log}")
            print(f"Module: {module_name}")
            return
        
        # Not passed, show error
        print(f"\n  Error/Output:\n{error_msg[:500]}")
        
        if attempt < args.max_attempts:
            print(f"\n  Retrying with different generation... ({attempt}/{args.max_attempts})")
        else:
            print("\n✗ FAILED: Max attempts reached without successful verification")
            return
    
    print("\n✗ FAILED: Unexpected error")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()