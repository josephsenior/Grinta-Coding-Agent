import sqlite3
import json
import os

try:
    conn = sqlite3.connect(".local/forge.db") # Wait, where is the db? Let me find the db file first!
    cursor = conn.cursor()
    cursor.execute("SELECT session_id, runtime_config FROM conversations ORDER BY updated_at DESC LIMIT 5")
    rows = cursor.fetchall()
    for row in rows:
        print(f"Session: {row[0]}")
        config = json.loads(row[1]) if row[1] else {}
        print(f"Workspace: {config.get('workspace_mount_path_in_runtime')}")
except Exception as e:
    print(e)
