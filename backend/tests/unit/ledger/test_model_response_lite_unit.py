"""Tests for backend.ledger.model_response_lite — Pydantic lite models."""

from __future__ import annotations

from types import SimpleNamespace

from backend.ledger.model_response_lite import (
    AssistantMessageLite,
    AssistantToolCallLite,
    ChoiceLite,
    ModelResponseLite,
)


class TestAssistantToolCallLite:
    def test_defaults(self):
        tc = AssistantToolCallLite()
        assert tc.id is None
        assert tc.function is None

    def test_custom(self):
        tc = AssistantToolCallLite(id='tc1', function={'name': 'bash'})
        assert tc.id == 'tc1'
        assert tc.function == {'name': 'bash'}


class TestAssistantMessageLite:
    def test_defaults(self):
        msg = AssistantMessageLite()
        assert msg.role is None
        assert msg.content is None
        assert msg.tool_calls is None

    def test_custom(self):
        tc = AssistantToolCallLite(id='tc1')
        msg = AssistantMessageLite(role='assistant', content='Hello', tool_calls=[tc])
        assert msg.role == 'assistant'
        assert msg.content == 'Hello'
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1


class TestChoiceLite:
    def test_defaults(self):
        c = ChoiceLite()
        assert c.message is None

    def test_with_message(self):
        msg = AssistantMessageLite(role='assistant')
        c = ChoiceLite(message=msg)
        assert c.message is not None
        assert c.message.role == 'assistant'


class TestModelResponseLiteModel:
    def test_defaults(self):
        r = ModelResponseLite()
        assert r.id is None
        assert r.model is None
        assert r.choices == []

    def test_get(self):
        r = ModelResponseLite(id='resp-1', model='gpt-4')
        assert r.get('id') == 'resp-1'
        assert r.get('model') == 'gpt-4'
        assert r.get('nonexistent', 'default') == 'default'

    def test_from_sdk_simple_namespace(self):
        resp = SimpleNamespace(
            id='resp-1',
            model='gpt-4',
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        role='assistant',
                        content='Hello',
                        tool_calls=None,
                    )
                )
            ],
        )
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.id == 'resp-1'
        assert lite.model == 'gpt-4'
        assert len(lite.choices) == 1
        assert lite.choices[0].message is not None
        assert lite.choices[0].message.role == 'assistant'
        assert lite.choices[0].message.content == 'Hello'

    def test_from_sdk_with_tool_calls(self):
        resp = SimpleNamespace(
            id='resp-2',
            model='claude-3',
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        role='assistant',
                        content=None,
                        tool_calls=[
                            SimpleNamespace(id='tc1', function={'name': 'bash'}),
                            SimpleNamespace(id='tc2', function={'name': 'edit'}),
                        ],
                    )
                )
            ],
        )
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices[0].message is not None
        assert lite.choices[0].message.tool_calls is not None
        assert len(lite.choices[0].message.tool_calls) == 2
        assert lite.choices[0].message.tool_calls[0].id == 'tc1'
        assert lite.choices[0].message.tool_calls[1].id == 'tc2'

    def test_from_sdk_dict(self):
        resp = {
            'id': 'resp-3',
            'model': 'mistral',
            'choices': [{'message': {'role': 'assistant', 'content': 'Hi'}}],
        }
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.id == 'resp-3'
        assert lite.model == 'mistral'

    def test_from_sdk_no_message(self):
        resp = SimpleNamespace(
            id='r', model='m', choices=[SimpleNamespace(message=None)]
        )
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices[0].message is None

    def test_from_sdk_empty_choices(self):
        resp = SimpleNamespace(id='r', model='m', choices=[])
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices == []

    def test_from_sdk_none_choices(self):
        resp = SimpleNamespace(id='r', model='m', choices=None)
        lite = ModelResponseLite.from_sdk(resp)
        assert lite.choices == []

    def test_getattr_or_get_dict(self):
        assert ModelResponseLite._getattr_or_get({'key': 'val'}, 'key') == 'val'

    def test_getattr_or_get_missing(self):
        assert ModelResponseLite._getattr_or_get(object(), 'foo', 'bar') == 'bar'
