"""Relay model-only requests from an offline container to the host subscription."""

import json
import queue
import subprocess
import threading

from openai import OpenAI

from backend.inference.clients.chatgpt_plan_auth import access_token


def relay(command, *, marker, budget, log, profile='default', on_stop=None):
    """Execute a trusted argv; account all inference and retain non-secret logs."""
    if not marker or '\n' in marker:
        raise ValueError('invalid relay marker')
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
    )
    lines = queue.Queue()

    def reader():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    budget.start()
    try:
        while True:
            budget.check()
            try:
                line = lines.get(timeout=min(1, budget.remaining))
            except queue.Empty:
                continue
            if line is None:
                return process.wait(timeout=10)
            if not line.startswith(marker):
                log.write(line)
                log.flush()
                continue
            payload = json.loads(line[len(marker) :])
            log.write('[model-request] starting subscription inference\n')
            log.flush()
            if (
                payload.get('model') != 'gpt-6.1-sol'
                or payload.get('reasoning', {}).get('effort') != 'medium'
                or payload.get('store') is not False
                or payload.get('stream') is not True
            ):
                raise ValueError('relay request differs from agreed model settings')
            # Never accept an endpoint, credential or host tool execution request.
            allowed = {
                'model',
                'reasoning',
                'instructions',
                'input',
                'tools',
                'tool_choice',
                'parallel_tool_calls',
                'store',
                'stream',
                'include',
            }
            if set(payload) - allowed:
                raise ValueError('unsupported relay request fields')
            budget.observe_request(payload)
            client = OpenAI(
                api_key=access_token(profile),
                base_url='https://api.openai.com/v1',
                max_retries=0,
                timeout=min(120, budget.remaining),
            )
            completed = None
            output_items = {}
            with client.responses.create(**payload) as stream:
                for event in stream:
                    budget.check()
                    if event.type in {
                        'response.failed',
                        'response.incomplete',
                        'error',
                    }:
                        raise RuntimeError('subscription relay response failed')
                    if event.type == 'response.output_item.done':
                        output_items[event.output_index] = event.item.model_dump(
                            mode='json'
                        )
                    if event.type == 'response.completed':
                        completed = event.response.model_dump(mode='json')
                        # Finalized item events carry tool arguments and text.
                        # Preserve them if the terminal response omits output.
                        output = dict(enumerate(completed.get('output') or []))
                        output.update(output_items)
                        completed['output'] = [output[i] for i in sorted(output)]
                        break
            if completed is None:
                raise RuntimeError('subscription relay response interrupted')
            usage = completed.get('usage') or {}
            budget.charge(usage.get('input_tokens'), usage.get('output_tokens'))
            budget.observe_response(completed.get('output', []))
            log.write('[model-usage] ' + json.dumps(budget.snapshot()) + '\n')
            log.write(
                '[model-output] '
                + json.dumps(
                    {
                        'types': [
                            item.get('type') for item in completed.get('output', [])
                        ],
                    }
                )
                + '\n'
            )
            log.flush()
            process.stdin.write(json.dumps({'response': completed}) + '\n')
            process.stdin.flush()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if on_stop:
            on_stop()
