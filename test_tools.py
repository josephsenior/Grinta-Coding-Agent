import asyncio  
from pydantic import SecretStr  
from backend.core.config.llm_config import LLMConfig  
from backend.llm.llm import LLM  
from dotenv import load_dotenv  
load_dotenv('.env.local')  
async def test():  
    config = LLMConfig(model='gemini-2.5-flash', api_key=SecretStr(''))  
    llm = LLM(service_id='test', config=config)  
    messages = [{'role': 'user', 'content': 'hello'}]  
    try:  
        async for c in llm.client.astream(messages, tools=[]):  
            pass  
        print('SUCCESS!')  
    except Exception as e:  
        print(f'CAUGHT EXCEPTION: {type(e)} {e}')  
asyncio.run(test())  
