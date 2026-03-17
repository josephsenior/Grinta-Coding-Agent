import os
import re

fpath = r"backend\llm\direct_clients.py"
with open(fpath, "r", encoding="utf-8") as f:
    code = f.read()

replacement = """        kwargs["stream"] = True
        kwargs.pop("model", None)
        try:
            for key in ("metadata", "user", "extra_body"):
                if key in kwargs:
                    _val = kwargs.pop(key)
                    print(f"!!! POPPED {key} from kwargs in astream !!!", _val, flush=True)
            for m in messages:
                if "metadata" in m: m.pop("metadata")
            stream = await self.async_client.chat.completions.create("""

code = code.replace("""        kwargs["stream"] = True
        kwargs.pop("model", None)
        try:
            stream = await self.async_client.chat.completions.create(""", replacement)

with open(fpath, "w", encoding="utf-8") as f:
    f.write(code)
print("patched astream")
