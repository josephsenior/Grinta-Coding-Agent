
import httpx
URL = "http://127.0.0.1:3000/api/v1/conversations/"
r_conv = httpx.post(URL, json={})
conv_id = r_conv.json()["conversation_id"]
r_start = httpx.post(f"{URL}{conv_id}/start", json={})
print("STATUS CODE:", r_start.status_code)
print("RESPONSE TEXT:", r_start.text)

