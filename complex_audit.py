import asyncio
from tui.client import ForgeClient
import time
import httpx
import os

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

    # Join conversation (websockets)
    await client.join_conversation(conv_id)
    print("Joined conversation websocket.")
    
    # Task Prompt
    task_prompt = (
        "Create a simple Flask application with three files: "
        "1) my_rest_app.py (the flask app), "
        "2) models.py (a simple User class), "
        "3) requirements.txt (with Flask). "
        "Create these files in a new directory called 'audit_test_project'. "
        "Then finish."
    )
    
    print("Sending complex multi-step task...")
    await client.send_message(task_prompt)
    
    print("Starting agent...")
    await client.start_agent(conv_id)
    
    print("Agent triggered. Auditing workspace changes every 5s for up to 60s...")
    start_time = time.time()
    seen_files = set()
    success = False
    
    while time.time() - start_time < 60:
        await asyncio.sleep(5)
        
        # Check files locally since we're in the same workspace!
        if os.path.exists("audit_test_project"):
            files = os.listdir("audit_test_project")
            for f in files:
                if f not in seen_files:
                    print(f"   [Audit] Detected new file created by agent: {f}")
                    seen_files.add(f)
            
            if "my_rest_app.py" in seen_files and "models.py" in seen_files and "requirements.txt" in seen_files:
                print("\n[SUCCESS] Agent successfully created all requested files!")
                success = True
                break

    if not success:
        print("\n[FAILED] Agent didn't create all targeted files in time.")
    
    await client.stop_agent(conv_id)
    await client.leave_conversation()
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
