import os
import re

fpath = r"backend\llm\direct_clients.py"
with open(fpath, "r", encoding="utf-8") as f:
    code = f.read()

# For astream
code = code.replace("for key in (\"metadata\", \"user\", \"extra_body\"):", "for key in (\"metadata\", \"user\", \"extra_body\", \"reasoning_effort\"):")

# For acompletion
code = code.replace("for key in (\"metadata\", \"user\", \"extra_body\"):", "for key in (\"metadata\", \"user\", \"extra_body\", \"reasoning_effort\"):")

with open(fpath, "w", encoding="utf-8") as f:
    f.write(code)
print("patched reasoning_effort")
