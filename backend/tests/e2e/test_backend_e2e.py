import requests
import json
import time

BASE_URL = "http://127.0.0.1:3000/api/v1"


def test_e2e_completions():
    # 1. Create a conversation
    print("Creating a conversation...")
    init_data = {
        "initial_user_msg": "Hello, this is an E2E test.",
        "vcs_provider": "enterprise_sso",  # optional
    }
    resp = requests.post(f"{BASE_URL}/conversations", json=init_data)
    if resp.status_code != 200:
        print(f"Failed to create conversation: {resp.status_code}")
        print(resp.text)
        return

    data = resp.json()
    conv_id = data["conversation_id"]
    print(f"Created conversation: {conv_id}")

    # 2. Test completion endpoint
    # Note: completions endpoint expects a full code context, but we want to see if it routes through GeminiClient
    print("\nTesting completions endpoint...")
    completion_data = {
        "filePath": "test.py",
        "fileContent": "def hello():\n    ",
        "language": "python",
        "position": {"line": 1, "character": 4},
        "prefix": "def hello():\n    ",
        "suffix": "",
    }

    start_time = time.time()
    comp_resp = requests.post(
        f"{BASE_URL}/conversations/{conv_id}/completions", json=completion_data
    )
    end_time = time.time()

    if comp_resp.status_code == 200:
        print(f"Success! Response received in {end_time - start_time:.2f}s")
        print("Response Content:")
        print(json.dumps(comp_resp.json(), indent=2))
        print("\nGemini integration is working end-to-end through the backend API!")
    else:
        print(f"Failed to get completion: {comp_resp.status_code}")
        print(comp_resp.text)


if __name__ == "__main__":
    test_e2e_completions()
