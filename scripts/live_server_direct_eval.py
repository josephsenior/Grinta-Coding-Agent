from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forge_client import ForgeClient

BASE_URL = os.environ.get("FORGE_BASE_URL", "http://127.0.0.1:3000")
FORGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(r"C:\Users\GIGABYTE\Desktop\New folder")
RESULTS_PATH = FORGE_ROOT / "live_server_direct_eval_results.json"
SERVER_LOG_PATH = FORGE_ROOT / "live_server_direct_eval_server.log"


def save_results(results: dict[str, Any]) -> None:
    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")


@dataclass
class ScenarioTrace:
    conversation_id: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    last_event_id: int = -1
    terminal_state: str | None = None
    tool_actions: list[str] = field(default_factory=list)
    disconnected_at_event_id: int | None = None

    def record(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        event_id = event.get("id")
        if isinstance(event_id, int):
            self.last_event_id = max(self.last_event_id, event_id)
        extras = event.get("extras") or {}
        state = extras.get("agent_state") if isinstance(extras, dict) else None
        if isinstance(state, str) and state:
            self.terminal_state = state.upper()
        action = str(event.get("action") or "")
        if action and action not in {
            "streaming_chunk",
            "message",
            "recall",
            "system_message",
            "change_agent_state",
            "add_memory",
        }:
            self.tool_actions.append(action)


def print_step(message: str) -> None:
    print(message, flush=True)


def request_json(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method, f"{BASE_URL}{path}", timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def wait_for_health(timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = requests.get(f"{BASE_URL}/api/health/ready", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # pragma: no cover - live probe
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"Server did not become healthy in {timeout}s: {last_error}")


def kill_server_processes() -> list[int]:
    killed: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if proc.info.get("name", "").lower() != "python.exe":
                continue
            if "start_server.py" in cmdline or "uvicorn" in cmdline:
                proc.kill()
                killed.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return killed


def start_server_subprocess() -> subprocess.Popen[str]:
    with SERVER_LOG_PATH.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "start_server.py"],
            cwd=str(FORGE_ROOT),
            stdout=log_file,
            stderr=log_file,
            text=True,
        )
    return proc


def reset_workspace() -> None:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    for child in WORKSPACE_ROOT.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def prepare_complex_refactor() -> None:
    reset_workspace()
    write_text(
        WORKSPACE_ROOT / "complex_refactor" / "reporting" / "__init__.py",
        "",
    )
    write_text(
        WORKSPACE_ROOT / "complex_refactor" / "reporting" / "stats.py",
        "def moving_average(values, window):\n"
        "    if window <= 0:\n"
        "        raise ValueError('window must be positive')\n"
        "    if len(values) < window:\n"
        "        return []\n"
        "    averages = []\n"
        "    for idx in range(len(values) - window):\n"
        "        chunk = values[idx:idx + window]\n"
        "        averages.append(sum(chunk) // window)\n"
        "    return averages\n\n"
        "def summarize(values):\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        total += value\n"
        "    average = total / len(values) if values else 0.0\n"
        "    return {'count': len(values), 'total': total, 'average': average}\n",
    )
    write_text(
        WORKSPACE_ROOT / "complex_refactor" / "reporting" / "formatting.py",
        "def format_summary(summary):\n"
        "    return f\"count={summary['count']} total={summary['total']} average={summary['average']:.2f}\"\n",
    )
    write_text(
        WORKSPACE_ROOT / "complex_refactor" / "test_reporting.py",
        "import unittest\n\n"
        "from reporting.formatting import format_summary\n"
        "from reporting.stats import moving_average, summarize\n\n\n"
        "class ReportingTests(unittest.TestCase):\n"
        "    def test_moving_average(self):\n"
        "        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])\n\n"
        "    def test_short_window(self):\n"
        "        self.assertEqual(moving_average([1, 2], 3), [])\n\n"
        "    def test_summary_format(self):\n"
        "        summary = summarize([2, 4, 6])\n"
        "        self.assertEqual(summary, {'count': 3, 'total': 12, 'average': 4.0})\n"
        "        self.assertEqual(format_summary(summary), 'count=3 total=12 average=4.00')\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
    )


def run_unittest(test_dir: str, pattern: str = "test*.py") -> tuple[bool, str]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            test_dir,
            "-p",
            pattern,
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, combined[-4000:]


async def create_conversation(client: ForgeClient) -> str:
    conv = await asyncio.wait_for(client.create_conversation(), timeout=180)
    conv_id = str(conv.get("conversation_id") or conv.get("id") or "")
    if not conv_id:
        raise RuntimeError(f"No conversation id in response: {conv}")
    await asyncio.wait_for(client.start_agent(conv_id), timeout=60)
    return conv_id


async def run_prompt(prompt: str, *, disconnect_after_tool: bool = False, disconnect_pause: float = 8.0) -> tuple[ScenarioTrace, bool]:
    trace = ScenarioTrace()
    terminal = asyncio.Event()
    first_tool = asyncio.Event()
    initialized = asyncio.Event()
    prompt_sent = False

    client = ForgeClient(BASE_URL)

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal prompt_sent
        trace.record(event)
        extras = event.get("extras") or {}
        state = str(extras.get("agent_state") or "").upper() if isinstance(extras, dict) else ""
        action = str(event.get("action") or "")
        if action and action not in {"streaming_chunk", "message", "recall", "system_message", "change_agent_state", "add_memory", "system"}:
            first_tool.set()
        if not prompt_sent and state == "AWAITING_USER_INPUT":
            initialized.set()
        elif state in {"AWAITING_USER_INPUT", "FINISHED", "STOPPED", "ERROR", "REJECTED"} or action == "finish":
            terminal.set()

    try:
        conv_id = await create_conversation(client)
        trace.conversation_id = conv_id
        await client.join_conversation(conv_id, on_event=on_event)
        await asyncio.wait_for(initialized.wait(), timeout=120)
        prompt_sent = True
        await client.send_message(prompt)

        if disconnect_after_tool:
            await asyncio.wait_for(first_tool.wait(), timeout=120)
            trace.disconnected_at_event_id = trace.last_event_id
            await client.leave_conversation()
            await asyncio.sleep(disconnect_pause)
            await client.join_conversation(conv_id, on_event=on_event, latest_event_id=trace.last_event_id)

        await asyncio.wait_for(terminal.wait(), timeout=300)
        return trace, True
    except Exception as exc:
        trace.events.append({"error": str(exc)})
        return trace, False
    finally:
        await client.close()


async def run_server_restart_scenario() -> dict[str, Any]:
    reset_workspace()
    prompt = (
        "Create a new folder `resume_suite`. Inside it create a small standard-library Python package with "
        "`resume_suite/core.py`, `resume_suite/__init__.py`, and `test_resume_suite.py`. "
        "Implement `slugify(text)` and `dedupe_keep_order(items)` with unittests, then run the tests."
    )
    trace = ScenarioTrace()
    terminal = asyncio.Event()
    progress = asyncio.Event()
    initialized = asyncio.Event()
    prompt_sent = False
    client = ForgeClient(BASE_URL)

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal prompt_sent
        trace.record(event)
        action = str(event.get("action") or "")
        extras = event.get("extras") or {}
        state = str(extras.get("agent_state") or "").upper() if isinstance(extras, dict) else ""
        if action and action not in {"streaming_chunk", "message", "recall", "system_message", "change_agent_state", "add_memory", "system"}:
            progress.set()
        if not prompt_sent and state == "AWAITING_USER_INPUT":
            initialized.set()
        elif state in {"AWAITING_USER_INPUT", "FINISHED", "STOPPED", "ERROR", "REJECTED"} or action == "finish":
            terminal.set()

    restart_proc: subprocess.Popen[str] | None = None
    try:
        conv_id = await create_conversation(client)
        trace.conversation_id = conv_id
        await client.join_conversation(conv_id, on_event=on_event)
        await asyncio.wait_for(initialized.wait(), timeout=120)
        prompt_sent = True
        await client.send_message(prompt)
        try:
            await asyncio.wait_for(progress.wait(), timeout=120)
        except TimeoutError:
            return {
                "conversation_id": conv_id,
                "error": "no_tool_progress_before_restart_injection",
                "event_count": len(trace.events),
                "last_event_id": trace.last_event_id,
                "terminal_state": trace.terminal_state,
                "tool_actions": trace.tool_actions,
            }
        await asyncio.sleep(2.0)

        killed = kill_server_processes()
        await client.leave_conversation()
        await asyncio.sleep(2.0)
        restart_proc = start_server_subprocess()
        health = wait_for_health(timeout=90)
        settings_snapshot = request_json("GET", "/api/v1/settings")

        reconnect_client = ForgeClient(BASE_URL)
        try:
            async def on_reconnect(event: dict[str, Any]) -> None:
                trace.record(event)
                extras = event.get("extras") or {}
                state = str(extras.get("agent_state") or "").upper() if isinstance(extras, dict) else ""
                if state in {"AWAITING_USER_INPUT", "FINISHED", "STOPPED", "ERROR", "REJECTED"} or str(event.get("action") or "") == "finish":
                    terminal.set()

            await reconnect_client.join_conversation(conv_id, on_event=on_reconnect, latest_event_id=trace.last_event_id)
            try:
                await asyncio.wait_for(terminal.wait(), timeout=90)
            except asyncio.TimeoutError:
                pass
        finally:
            await reconnect_client.close()

        conv_state = None
        try:
            conv_payload = request_json("GET", f"/api/v1/conversations/{conv_id}")
            conv_state = conv_payload.get("agent_state")
        except Exception as exc:
            conv_state = f"lookup_failed: {exc}"

        test_ok, test_output = run_unittest("resume_suite")
        return {
            "conversation_id": conv_id,
            "killed_pids": killed,
            "health_project_root": health.get("config", {}).get("project_root"),
            "health_recovery": health.get("recovery"),
            "settings_recovery": settings_snapshot.get("recovery_snapshot"),
            "conversation_state_after_restart": conv_state,
            "event_count": len(trace.events),
            "last_event_id": trace.last_event_id,
            "tool_actions": trace.tool_actions,
            "tests_passed": test_ok,
            "test_output_tail": test_output,
        }
    finally:
        await client.close()
        if restart_proc is not None:
            restart_proc.terminate()
            try:
                restart_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                restart_proc.kill()


async def main() -> int:
    results: dict[str, Any] = {
        "health_before": wait_for_health(timeout=30),
    }
    save_results(results)

    print_step("Scenario 1: complex fix challenge")
    try:
        prepare_complex_refactor()
        trace1, ok1 = await run_prompt(
            "In `complex_refactor`, make `python -m unittest complex_refactor.test_reporting` pass. Fix the root causes, keep the existing public functions, add concise module or function docstrings where they are missing, and run the tests.",
        )
        tests_ok1, test_output1 = run_unittest("complex_refactor")
        stats_path = WORKSPACE_ROOT / "complex_refactor" / "reporting" / "stats.py"
        results["complex_fix"] = {
            "conversation_id": trace1.conversation_id,
            "success": ok1,
            "event_count": len(trace1.events),
            "last_event_id": trace1.last_event_id,
            "terminal_state": trace1.terminal_state,
            "tool_actions": trace1.tool_actions,
            "tests_passed": tests_ok1,
            "test_output_tail": test_output1,
            "stats_py_tail": stats_path.read_text(encoding="utf-8")[-1200:] if stats_path.exists() else None,
        }
    except Exception as exc:
        results["complex_fix"] = {"error": str(exc)}
    save_results(results)

    print_step("Scenario 2: websocket disconnect and reconnect")
    try:
        reset_workspace()
        trace2, ok2 = await run_prompt(
            "Create a folder `resilience_app`. Inside it create a standard-library Python package with `resilience_app/__init__.py`, `resilience_app/tasks.py`, `resilience_app/cli.py`, and `test_tasks.py`. Implement `parse_tasks(text)` to parse `[x] done` and `[ ] pending` lines, plus `summarize_tasks(tasks)` returning total/completed/pending counts. Add unittests and run them.",
            disconnect_after_tool=True,
            disconnect_pause=10.0,
        )
        tests_ok2, test_output2 = run_unittest("resilience_app")
        results["disconnect_reconnect"] = {
            "conversation_id": trace2.conversation_id,
            "success": ok2,
            "event_count": len(trace2.events),
            "last_event_id": trace2.last_event_id,
            "terminal_state": trace2.terminal_state,
            "tool_actions": trace2.tool_actions,
            "disconnected_at_event_id": trace2.disconnected_at_event_id,
            "tests_passed": tests_ok2,
            "test_output_tail": test_output2,
        }
    except Exception as exc:
        results["disconnect_reconnect"] = {"error": str(exc)}
    save_results(results)

    print_step("Scenario 3: server restart during active work")
    try:
        results["server_restart"] = await run_server_restart_scenario()
    except Exception as exc:
        results["server_restart"] = {"error": str(exc)}

    save_results(results)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
