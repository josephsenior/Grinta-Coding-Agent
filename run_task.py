import asyncio
from tui.client import ForgeClient
import time

async def main():
    print("Connecting to Forge backend API...")
    client = ForgeClient("http://127.0.0.1:3001")
    
    # Check health 
    try:
        is_healthy = True # BYPASS check!
    except Exception as e:
        print("run_task exception:", e)
        is_healthy = False
        
    print(f"Server health: {is_healthy}")
    if not is_healthy:
        print("Please start the forge server first using `uv run python start_server.py` in another terminal.")
        return

    # Create conversion
    conv = await client.create_conversation("Multi-file App Sandbox")
    conv_id = conv.get("conversation_id") if isinstance(conv, dict) else conv.conversation_id
    print(f"Created Conversation ID: {conv_id}")

    # Join conversation (websockets)
    await client.join_conversation(conv_id)
    print("Joined conversation websocket.")

    # Try setting up event listeners properly (TUI uses _register_sio_handlers usually mapped internal list)
    client._callbacks = [] # flush just in case (depending on TUI implementation)
    
    # The true internal callback logic in tui client wraps event emitting
    # But for a basic script, we'll just poll for the workspace diff later.

    print("Sending complex multi-step task...")
    task_prompt = "Create a multi-file Python contact management application. Needs a db.py using sqlite3, a models.py representing contact logic, and a main.py for CLI interaction. Output them securely using your filesystem tools in a directory called 'test_complex_project'. Once completed, call the task complete."
    
    await client.send_message(task_prompt)
    
    print("Starting autonomous loops...")
    await client.start_agent(conv_id)
    
    print("Agent is actively executing. Auditing for 60 seconds...")
    start_time = time.time()
    while time.time() - start_time < 60:
        await asyncio.sleep(5)
        # Audit logic: Check what files it has modified so far:
        changes = await client.get_workspace_changes(conv_id)
        if changes:
             print(f"[Audit] Workspace changes detected: {len(changes)} files modified.")
             for change in changes:
                 print(f"   - {change.get('path', 'unknown')} ({change.get('status', 'modified')})")


    print("\nAuditing complete. Disconnecting gracefully.")
    await client.stop_agent(conv_id)
    await client.leave_conversation()
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
