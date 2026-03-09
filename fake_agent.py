import asyncio
import os
import subprocess
import time
import glob
import threading

def run_test():
    proc = subprocess.Popen(["uv", "run", "python", "complex_audit3.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    conv_id = None
    for line in iter(proc.stdout.readline, ''):
        print(line, end="", flush=True)
        if "Created Conversation ID:" in line:
            conv_id = line.strip().split()[-1]
            break
            
    if not conv_id:
        print("Could not find conversation ID")
        proc.wait()
        return

    # Start a background thread to look for the workspace and inject the file
    def inject():
        print(f"[Injector] Looking for workspace for {conv_id}...")
        base_temp = os.environ.get("TEMP", r"C:\Users\GIGABYTE\AppData\Local\Temp")
        
        for _ in range(60): # wait up to 60 seconds
            time.sleep(1)
            all_dirs = glob.glob(os.path.join(base_temp, "FORGE_workspace_*"))
            matches = [d for d in all_dirs if conv_id in d]
            if not matches and _ % 10 == 0:
                 print(f"[Injector] Found {len(all_dirs)} workspaces. None match {conv_id}. E.g.: {all_dirs[:2] if all_dirs else 'none'}")
            
            if matches:
                ws_dir = matches[0]
                print(f"[Injector] Found workspace: {ws_dir}!")
                # Give the agent a couple seconds to actually write the git init stuff so we don't race it
                time.sleep(3)
                os.makedirs(os.path.join(ws_dir, "audit_task"), exist_ok=True)
                with open(os.path.join(ws_dir, "audit_task", "my_rest_app.py"), "w") as f:
                    f.write("# fake flask application\n")
                
                # Make sure it's a git repo! The agent might have crashed before running it.
                subprocess.run(["git", "init"], cwd=ws_dir)
                subprocess.run(["git", "config", "user.name", "Tester"], cwd=ws_dir)
                subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=ws_dir)
                # optionally make an initial commit so git rev-parse HEAD doesn't fail, but our logic handles empty repos!
                # Wait, earlier we found git doesn't like checking untracked files on totally empty repos sometimes in Python? No, our logic handles it!
                print("[Injector] File and git init injected!")
                return
        print("[Injector] Gave up looking for workspace!")

    threading.Thread(target=inject, daemon=True).start()

    # Continue pumping output
    for line in iter(proc.stdout.readline, ''):
        print(line, end="", flush=True)

    proc.wait()

if __name__ == "__main__":
    run_test()
