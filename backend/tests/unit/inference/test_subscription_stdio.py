import io
import json

from backend.inference.clients.subscription_stdio import PipeResponses


def test_pipe_carries_only_payload_and_completed_response(monkeypatch):
    import sys

    output = io.StringIO()
    monkeypatch.setenv('GRINTA_SUBSCRIPTION_STDIO', 'MARK:')
    monkeypatch.setattr(sys, '__stdout__', output)
    monkeypatch.setattr(
        sys, '__stdin__', io.StringIO(json.dumps({'response': {'id': 'test'}}) + '\n')
    )
    events = list(PipeResponses().create(model='gpt-6.1-sol', input=[]))
    assert output.getvalue().startswith('MARK:')
    assert json.loads(output.getvalue()[5:]) == {'model': 'gpt-6.1-sol', 'input': []}
    assert events == [{'type': 'response.completed', 'response': {'id': 'test'}}]
