import os
import glob

tools_dir = "backend/engines/orchestrator/tools"
files = glob.glob(os.path.join(tools_dir, "*.py"))

replace_str = 'os.environ.get("FORGE_WORKSPACE_DIR", ".")'
new_str = 'load_forge_config(set_logging_levels=False).workspace_base or "."'
import_str = "from backend.core.config.utils import load_forge_config\n"

for path in files:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if replace_str in content:
        if import_str not in content:
            if "from __future__ import annotations" in content:
                content = content.replace("from __future__ import annotations", "from __future__ import annotations\n" + import_str)
            else:
                content = import_str + content
                
        content = content.replace(replace_str, new_str)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Patched {path}")
