import asyncio
import httpx
from tui.client import ForgeClient

async def main():
    client = ForgeClient("http://127.0.0.1:3000")
    print("Created Conversation ID...")
    conv = await client.create_conversation("Multi-file Audit App")
    conv_id = conv.get("conversation_id") if isinstance(conv, dict) else conv.conversation_id
    
    print(conv_id)
    await client.join_conversation(conv_id)
    
    task_prompt = "Hello"
    await client.send_message(task_prompt)
    await client.start_agent(conv_id)
    
    # Try fetching changes
    for _ in range(10):
        await asyncio.sleep(2)
        async with httpx.AsyncClient(timeout=30.0) as fetch_client:
            r = await fetch_client.get(f"http://127.0.0.1:3000/api/v1/conversations/{conv_id}/files/git/changes")
            print(f"Status: {r.status_code}, Body: {r.text[:200]}")
    await client.stop_agent(conv_id)
    await client.leave_conversation()
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
