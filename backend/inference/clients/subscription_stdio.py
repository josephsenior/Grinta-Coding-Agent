"""Model-only pipe transport for offline task containers.

The host relay owns OAuth. The pipe carries inference payloads and completed
responses only; it never grants host shell or file execution.
"""

import asyncio
import json
import os
import sys
import threading
from types import SimpleNamespace

_lock = threading.Lock()


class PipeResponses:
    def create(self, **payload):
        marker = os.environ['GRINTA_SUBSCRIPTION_STDIO']
        with _lock:
            sys.__stdout__.write(marker + json.dumps(payload) + '\n')
            sys.__stdout__.flush()
            line = sys.__stdin__.readline()
            if not line:
                raise RuntimeError('Host model relay disconnected')
            reply = json.loads(line)
            if reply.get('error'):
                raise RuntimeError('Host model relay failed')
        return iter([{'type': 'response.completed', 'response': reply['response']}])


class AsyncPipeResponses:
    async def create(self, **payload):
        events = await asyncio.to_thread(PipeResponses().create, **payload)

        async def stream():
            for event in events:
                yield event

        return stream()


def pipe_client(asynchronous=False):
    return SimpleNamespace(
        responses=AsyncPipeResponses() if asynchronous else PipeResponses()
    )
