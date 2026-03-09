import httpx
import time
import sys
import os

BASE_URL = "http://127.0.0.1:3001/api/v1"

def create_conversation():
    print("Creating conversation...")
    req = httpx.post(f"{BASE_URL}/conversations", json={}, timeout=60.0)
    req.raise_for_status()
    conv_id = req.json().get("conversation_id")
    print(f"Conversation initialized: {conv_id}")
    return conv_id

def send_prompt(conv_id, text):
    print("Sending prompt...")
    req = httpx.post(f"{BASE_URL}/conversations/{conv_id}/events/raw", content=text, headers={"Content-Type": "text/plain"}, timeout=60.0)
    req.raise_for_status()

def start_agent(conv_id):
    print("Starting autonomous agent...")
    req = httpx.post(f"{BASE_URL}/conversations/{conv_id}/start", json={}, timeout=60.0)
    req.raise_for_status()
    
def get_events(conv_id, start_id=0):
    req = httpx.get(f"{BASE_URL}/conversations/{conv_id}/events?limit=100&start_id={start_id}", timeout=60.0)
    if req.status_code == 200:
        return req.json().get("events", [])
    return []

def main():
    try:
        httpx.get("http://127.0.0.1:3000/alive").raise_for_status()
    except Exception:
        print("Backend server is not reachable. Is it running?")
        sys.exit(1)
        
    conv_id = create_conversation()
    
    prompt = (
        "Create a simple multi-file Python contact management application. "
        "Create a directory named exactly 'test_complex_project' under the workspace. "
        "Inside it, create `db.py` (sqlite3 initialization), `models.py` (data structures), "
        "and `main.py` (CLI interface to add/list contacts). "
        "Ensure the app runs locally. Write the source files using the appropriate filesystem tools."
    )
    
    send_prompt(conv_id, prompt)
    start_agent(conv_id)
    
    print("Agent is actively executing. Auditing for up to 90 seconds...")
    print("-" * 50)
    
    start_time = time.time()
    seen_events = set()
    latest_id = 0
    
    while time.time() - start_time < 90:
        time.sleep(2)
        events = get_events(conv_id, latest_id)
        
        for e in events:
            eid = e.get("id")
            if not eid:
                continue
            latest_id = max(latest_id, eid + 1)
            
            if eid not in seen_events:
                seen_events.add(eid)
                source = e.get("source", "")
                type_ = e.get("type", "")
                
                if type_ == "action" and e.get("action") == "tool_call":
                    tool = e.get("tool", "")
                    args = e.get("args", {})
                    # Truncate args output to avoid huge CLI logs
                    arg_str = str(args)[:100] + ("..." if len(str(args)) > 100 else "")
                    print(f"[AGENT TOOL_CALL] -> {tool} \n  Args: {arg_str}")
                    
                elif type_ == "observation" and e.get("observation") == "cmd_output":
                    print(f"[SYSTEM OUTPUT] -> {str(e.get('content', ''))[:100]}...")
                    
                elif type_ == "observation" and e.get("observation") == "error":
                    print(f"[SYSTEM ERROR/RECOVERY] -> {e.get('content', '')}")
                    
                elif type_ == "action" and e.get("action") == "message":
                    content = e.get("content", "")
                    if source == "agent":
                        print(f"[AGENT NOTE] => {content[:150]}...")
                        
        # Check if agent stopped
        req = httpx.get(f"{BASE_URL}/conversations/{conv_id}")
        if req.status_code == 200:
            status = req.json().get("status", "")
            if status not in ("running", "starting"):
                print(f"\nAgent loop finished. Final Status: {status}")
                break
            
    print("\nAudit Complete.")

if __name__ == "__main__":
    main()
