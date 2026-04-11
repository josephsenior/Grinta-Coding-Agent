import os
import sys
import subprocess
from unittest.mock import patch
import backend.engine.tools.prompt as prompt_mod

def run_test(label, cmd_string, shell_cmd, shell_args):
    print(f"\n[{label}] COMMAND to RUN: {cmd_string[:100]}...")
    res = subprocess.run(shell_cmd + shell_args + [cmd_string], capture_output=True, text=True)
    if res.returncode != 0:
         print(f"[{label}] ERROR {res.returncode}")
         print(f"STDOUT: {res.stdout.strip()}")
         print(f"STDERR: {res.stderr.strip()}")
    else:
         print(f"[{label}] SUCCESS!")
         print(f"STDOUT: {res.stdout.strip()[:100]}...")

def test_tool(name, py_script):
    print(f"=== Testing Tool: {name} ===")
    prompt_mod._get_global_tool_registry.cache_clear()
    
    # Test Bash
    with patch('backend.engine.tools.prompt.uses_powershell_terminal', return_value=False):
        bash_cmd = prompt_mod.build_python_exec_command(py_script)
        run_test(f"{name} (Bash)", bash_cmd, ["bash", "-c"], [])

    prompt_mod._get_global_tool_registry.cache_clear()

    # Test PowerShell
    with patch('backend.engine.tools.prompt.uses_powershell_terminal', return_value=True):
        ps_cmd = prompt_mod.build_python_exec_command(py_script)
        run_test(f"{name} (PowerShell)", ps_cmd, ["powershell", "-NoProfile", "-Command"], [])

if __name__ == '__main__':
    # 1. Dummy script
    test_tool("Dummy Print", "print('hello from python')")

    # 2. apply_patch simulation
    apply_patch_script = '''
import sys
print("Simulating apply_patch")
sys.exit(0)
'''
    test_tool("Apply Patch Sim", apply_patch_script)

    # 3. analyze_project_structure (simplified)
    tree_script = '''
import os
print("Simulating analyze_project_structure")
'''
    test_tool("Analyze Structure Sim", tree_script)
