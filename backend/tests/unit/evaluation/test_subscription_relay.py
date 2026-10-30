"""Verify the host relay delivers finalized streamed tool calls offline."""

import io
import json
import sys
from types import SimpleNamespace as NS

import pytest

from backend.inference.comparison_budget import AttemptBudget
from evaluation.deepswe import subscription_relay


@pytest.mark.parametrize('once_only', [False, True])
def test_relay_retains_tool_item_when_completed_event_has_no_output(
    monkeypatch, once_only
):
    item = {
        'type': 'function_call',
        'id': 'fc1',
        'call_id': 'call1',
        'name': 'read_file',
        'arguments': '{"path":"a.py"}',
    }

    class Stream:
        def __enter__(self):
            return iter(
                [
                    NS(
                        type='response.output_item.done',
                        output_index=0,
                        item=NS(model_dump=lambda **kwargs: item),
                    ),
                    NS(
                        type='response.completed',
                        response=NS(
                            model_dump=lambda **kwargs: {
                                'id': 'response1',
                                'output': [],
                                'usage': {'input_tokens': 10, 'output_tokens': 5},
                            }
                        ),
                    ),
                ]
            )

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(subscription_relay, 'access_token', lambda profile: 'offline')
    monkeypatch.setattr(
        subscription_relay,
        'OpenAI',
        lambda **kwargs: NS(responses=NS(create=lambda **payload: Stream())),
    )
    payload = {
        'model': 'gpt-6.1-sol',
        'reasoning': {'effort': 'medium'},
        'store': False,
        'stream': True,
        'input': [],
    }
    # A real child process speaks the same request/reply pipe protocol.
    script = (
        'import json,sys; '
        f'print("MARK:"+{json.dumps(json.dumps(payload))},flush=True); '
        'r=json.loads(sys.stdin.readline()); '
        f'assert r["response"]["output"]=={[item]!r}; '
        'print("tool delivered",flush=True)'
    )
    budget = AttemptBudget.pilot() if once_only else AttemptBudget()
    log = io.StringIO()
    assert (
        subscription_relay.relay(
            [sys.executable, '-c', script], marker='MARK:', budget=budget, log=log
        )
        == 0
    )
    assert budget.snapshot()['processed_tokens'] == 15
    assert budget.snapshot()['used_tokens'] > 0
    assert 'tool delivered' in log.getvalue()
