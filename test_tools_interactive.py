import subprocess

def run_in_shell(cmd_str, is_ps=False):
    shell_exe = "powershell" if is_ps else "bash"
    print(f"--- Running in {shell_exe} ---")
    args = [shell_exe, "-c", cmd_str]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=10)
        print("STDOUT:", res.stdout.strip())
        print("STDERR:", res.stderr.strip())
        print("EXIT:", res.returncode)
        return res.stdout, res.stderr, res.returncode
    except Exception as e:
        print("EXECUTION FAILED:", e)

# 1. Test what happens if we run bash 'grep' in powershell
print("\n=== Test 1: grep in powershell ===")
run_in_shell("grep -rn 'def' backend/engine/tools", is_ps=True)

# 2. Test what happens if we run 'ls' in powershell
print("\n=== Test 2: bare ls in powershell ===")
run_in_shell("ls backend/engine/tools | head -n 3", is_ps=True)

# 3. Test what happens if we run PS command in bash
print("\n=== Test 3: Get-ChildItem in bash ===")
run_in_shell("Get-ChildItem", is_ps=False)
