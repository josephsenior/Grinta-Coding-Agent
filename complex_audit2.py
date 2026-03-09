import asyncio
from tui.client import ForgeClient
import time
import httpx
import sys

async def main():
    print("Checking if Forge backend is ready...")
    for _ in range(5):
        try:
            r = httpx.get("http://127.0.0.1:3000/api/health/live")
            if r.status_code == 200:
                print("Server is up!")
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        print("Server not responding.")
        return

    print("Connecting to Forge backend API...")
    client = ForgeClient("http://127.0.0.1:3000")
    
    # Create conversion
    conv = await client.create_conversation("Multi-file Audit App")
    conv_id = conv.get("conversation_id") if isinstance(conv, dict) else conv.conversation_id
    print(f"Created Conversation ID: {conv_id}")

    # Join conversation
    await client.join_conversation(conv_id)
    print("Joined conversation websocket.")
    
    # Task Prompt
    task_prompt = (
        "Create a directory named 'audit_task' and inside it create three files: "
        "1) my_rest_app.py (a simple flask application), "
        "2) models.py (a simple class definition), "
        "3) requirements.txt (must contain Flask). "
        "Complete the task once these are correctly written."
    )
    
    print("Sending complex multi-step task...")
    await client.send_message(task_prompt)
    
    print("Starting agent...")
    await client.start_agent(conv_id)
    
    print("Agent triggered. Auditing workspace changes every 5s for up to 60s...")
    start_time = time.time()
    success = False
    
    # Track files
    seen_files = {}

    while time.time() - start_time < 90:
        await asyncio.sleep(5)
        
        try:
            changes = await client.get_workspace_changes(conv_id)
            for change in changes:
                path = change.get("path", change.get("path"))
                if path and path not in seen_files:
                    print(f"   [Audit] Detected agent action on file: {path} ({change.get('status', 'modified')})")
                    seen_files[path] = change
                    
            # Check success condition
            has_app = any("my_rest_app.py" in k for k in seen_files.keys())
            has_models = any("models.py" in k for k in seen_files.keys())
            has_req = any("requirements.txt" in k for k in seen_files.keys())
            
            if has_app and has_models and has_req:
                print("\n[SUCCESS] Agent successfully created all requested files! The multi-file application was built.")
                success = True
                break
        except Exception as e:
            print(f"Exception listing workspace changes: {e}")

    if not success:
        print("\n[FAILED] Agent didn't create all targeted files in time.")
        print(f"Final files: {list(seen_files.keys())}")
    
    await client.stop_agent(conv_id)
    await client.leave_conversation()
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())