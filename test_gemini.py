import os
import asyncio
from google import genai
import json

async def main():
    with open('settings.json') as f:
        settings = json.load(f)
        api_key = settings['llm']['api_key']
    
    os.environ['GEMINI_API_KEY'] = api_key
    client = genai.Client()
    
    # Test with tools=[]
    try:
        print("Testing with tools=[]...")
        chat = client.aio.chats.create(model='gemini-pro-latest', config={'tools': []})
        response = await chat.send_message_stream('hello')
        async for chunk in response:
            print(chunk.text)
        print("Test complete.")
    except Exception as e:
        print(f'Error: {type(e).__name__} - {e}')

asyncio.run(main())
