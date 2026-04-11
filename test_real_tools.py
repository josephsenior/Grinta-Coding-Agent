import sys
import subprocess
from unittest.mock import patch
import backend.engine.tools.prompt as prompt_mod
import backend.engine.tools.analyze_project_structure as analyze_mod
import backend.engine.tools.apply_patch as patch_mod

def run_test(label, cmd_string, shell_cmd, shell_args):
    print(f"\n[{label}] COMMAND: {cmd_string[:80]}...")
    res = subprocess.run(shell_cmd + shell_args + [cmd_string], capture_output=True, text=True)
    if res.returncode != 0:
         print(f"[{label}] ERROR {res.returncode}")
         print(f"STDOUT: {res.stdout.strip()[:200]}")
         print(f"STDERR: {res.stderr.strip()[:200]}")
    else:
         print(f"[{label}] SUCCESS!")
         print(f"STDOUT: {res.stdout.strip()[:100]}...")

def test_tool_action(name, generate_action_fn, args_dict):
    print(f"\n======================================")
    print(f"=== Testing Tool: {name} ===")
    
    prompt_mod._get_global_tool_registry.cache_clear()
    with patch('backend.engine.tools.prompt.uses_powershell_terminal', return_value=False):
        action = generate_action_fn(args_dict)
        if hasattr(action, 'command'):
            run_test(f"{name} (Bash)", action.command, ["bash", "-c"], [])

    prompt_mod._get_global_tool_registry.cache_clear()
    with patch('backend.engine.tools.prompt.uses_powershell_terminal', return_value=True):
        action = generate_action_fn(args_dict)
        if hasattr(action, 'command'):
            run_test(f"{name} (PowerShell)", action.command, ["powershell", "-NoProfile", "-Command"], [])

if __name__ == '__main__':
    test_tool_action("Analyze Project Structure", analyze_mod.build_analyze_project_structure_action, {"path":"backend", "depth":1, "type": "tree"})
    
    dummy_patch = '''diff --git a/dummy.txt b/dummy.txt
new file mode 100644
index 0000000..8b13789
--- /dev/null
+++ b/dummy.txt
@@ -0,0 +1 @@
+hello
'''
    test_tool_action("Apply Patch (Dry Run)", patch_mod.build_apply_patch_action, {"patch":dummy_patch, "check_only":True})

    print("Success")
