import asyncio
from tui.client import ForgeClient
import time

async def main():
    client = ForgeClient("http://127.0.0.1:3000")
    
    async def on_event(data):
        print(f"WS EVENT: {data}")
    
    client._event_callback = on_event
    conv = await client.create_conversation("Simple test")
    conv_id = conv.get("conversation_id") if isinstance(conv, dict) else conv.conversation_id
    await client.join_conversation(conv_id)
    await client.send_message("Create a single file called test.py with print('hello')")
    await client.start_agent(conv_id)
    
    # Keep the task alive and processing events
    for _ in range(10):
        await asyncio.sleep(2)

    await client.stop_agent(conv_id)
    await client.close()

if __name__ == '__main__':
    asyncio.run(main())
