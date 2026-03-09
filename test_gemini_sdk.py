
import os
from google import genai
client = genai.Client(api_key="AIzaSyAM_SJaVTacapIW9FtZcVoIzQY_igKiE5Q")
try:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Say hi"
    )
    print("SUCCESS!", response.text)
except Exception as e:
    import traceback
    traceback.print_exc()

