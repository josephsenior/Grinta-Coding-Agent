
import os
def go():
    os.environ['GEMINI_API_KEY']=open('.env.local').read().split('GEMINI_API_KEY=')[1].split('\n')[0].strip()
    from backend.core.config.api_key_manager import api_key_manager
    key_obj = api_key_manager.get_api_key_for_model('gemini-2.5-flash', None)
    key_val = key_obj.get_secret_value() if key_obj else None
    print('Key starts with:', key_val[:20] if key_val else None)
go()

