import base64
t = open(r'c:\Users\GIGABYTE\AppData\Roaming\Code - Insiders\User\workspaceStorage\062ba6bd841717cd3234fd19254d9fe4\GitHub.copilot-chat\chat-session-resources\acef0b82-bd45-4ec0-96cd-e69889a36fda\call_MHxFdWNCTTNYTmloUlJ0bVlRdlU__vscode-1776159905675\content.txt').read()
en = t.split(\"b'\")[1].split(\"')\")[0]
open('gen.py', 'w').write(base64.b64decode(en).decode())
