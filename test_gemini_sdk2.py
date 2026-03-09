
from google import genai
from google.genai.types import HttpOptions
http_options = HttpOptions(timeout=120000)
client = genai.Client(api_key="AIzaSyAM_SJaVTacapIW9FtZcVoIzQY_igKiE5Q", http_options=http_options)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say hi"
)
print("SUCCESS!", response.text)

