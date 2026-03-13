"""Check for FORGE_workspace leaks in a conversation's events."""
import json, os, re, sys

conv_id = sys.argv[1] if len(sys.argv) > 1 else "969cedd1e2bd4999b832ac86915a0c81"
d = f"storage/users/oss_user/conversations/{conv_id}/events"

for f in sorted(os.listdir(d), key=lambda x: int(x.split('.')[0])):
    path = os.path.join(d, f)
    txt = open(path).read()
    if "FORGE_workspace" in txt:
        # Find exact locations
        matches = re.findall(r'.{0,40}FORGE_workspace.{0,60}', txt)
        print(f"\n=== {f} ===")
        for m in matches:
            print(f"  {m}")
