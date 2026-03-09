
import os
from dotenv import load_dotenv
load_dotenv(".env.local")
from backend.core.config.api_key_manager import api_key_manager
key = api_key_manager.get_api_key_for_model("gemini-2.5-flash", None)
print(f"KEY FOUND: {key is not None}")
if key:
    print(f"VALUE: {key.get_secret_value()}")

