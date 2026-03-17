import os
import re

fpath = r"backend\llm\direct_clients.py"
with open(fpath, "r", encoding="utf-8") as f:
    code = f.read()

replacement = """        kwargs.pop("model", None)
        try:
            import json
            if "metadata" in kwargs: print("!!! KWARGS HAS METADATA !!!", flush=True)
            for key in ("metadata", "user", "extra_body"):
                if key in kwargs:
                    _val = kwargs.pop(key)
                    print(f"!!! POPPED {key} from kwargs to avoid Moonshot errors !!!", _val, flush=True)
            for m in messages:
                if "metadata" in m:
                    print("!!! MESSAGE HAS METADATA !!!", m["metadata"], flush=True)
            response = await self.async_client.chat.completions.create("""

code = code.replace("""        kwargs.pop("model", None)
        try:
            response = await self.async_client.chat.completions.create(""", replacement)

with open(fpath, "w", encoding="utf-8") as f:
    f.write(code)
print("patched")
