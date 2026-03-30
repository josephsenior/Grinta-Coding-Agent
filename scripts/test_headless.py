"""Headless agent test — validates core agent loop end-to-end."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from client import AppClient

SERVER = os.environ.get("APP_BASE_URL", "http://localhost:3000")
TIMEOUT = 600  # 10 min max per task


def _agent_state(event: dict) -> str:
    extras = event.get("extras") or {}
    if isinstance(extras, dict):
        state = extras.get("agent_state")
        if isinstance(state, str) and state:
            return state.upper()
    return ""


async def run_task(description: str, task: str) -> dict:
    """Run a single agent task and return results."""
    print(f"\n{'='*60}")
    print(f"TASK: {description}")
    print(f"{'='*60}")

    client = AppClient(base_url=SERVER)
    tool_calls = []
    final_status = None
    t0 = time.time()
    terminal = asyncio.Event()

    try:
        conv = await client.create_conversation(initial_message=task)
        conv_id = conv.get("id") or conv.get("conversation_id")
        if not conv_id:
            raise ValueError(f"No conversation ID in: {conv}")
        print(f"  Conversation: {conv_id}")

        # Collect events
        async def on_event(event):
            nonlocal final_status
            action = event.get("action")
            observation = event.get("observation")
            state = _agent_state(event)
            elapsed = time.time() - t0

            if action and action not in ("streaming_chunk",):
                print(f"  [{elapsed:6.1f}s] action={action}")
                if action not in ("message",):
                    tool_calls.append(action)
            if observation and observation != "agent_state_changed":
                print(f"  [{elapsed:6.1f}s] observation={observation}")
            if state:
                print(f"  [{elapsed:6.1f}s] state={state}")
                if state in ("FINISHED", "STOPPED", "ERROR", "REJECTED"):
                    final_status = state
                    terminal.set()
            if action == "finish":
                final_status = "FINISHED"
                terminal.set()

        await client.join_conversation(conv_id, on_event=on_event)
        await asyncio.sleep(0.5)

        await client.start_agent(conv_id)

        # Wait for terminal status
        try:
            await asyncio.wait_for(terminal.wait(), timeout=TIMEOUT)
        except TimeoutError:
            pass

        elapsed = time.time() - t0
        if final_status is None:
            print(f"  TIMEOUT after {elapsed:.0f}s ({len(tool_calls)} tool calls)")
        else:
            print(f"  Completed: {final_status} in {elapsed:.1f}s with {len(tool_calls)} tool calls")

    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR after {elapsed:.1f}s: {e}")
        final_status = f"EXCEPTION: {e}"
    finally:
        await client.close()

    return {
        "description": description,
        "status": final_status,
        "tool_calls": tool_calls,
        "elapsed": time.time() - t0,
    }


async def main():
    results = []

    # Task 1: Simple file creation (minimal — should finish fast)
    r = await run_task(
        "Create a single Python file",
        "Create a file called hello.py that prints 'Hello, World!' and save it.",
    )
    results.append(r)

    # Task 2: Read + analyze (tests tool usage)
    r = await run_task(
        "Read and summarize a file",
        "Read the file pyproject.toml and tell me the project name and version.",
    )
    results.append(r)

    # Summary
    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for r in results:
        status = r["status"] or "TIMEOUT"
        print(f"  {r['description']}: {status} | {r['elapsed']:.0f}s | {len(r['tool_calls'])} tools")
        if r["tool_calls"]:
            print(f"    Tools: {', '.join(r['tool_calls'])}")


if __name__ == "__main__":
    asyncio.run(main())
