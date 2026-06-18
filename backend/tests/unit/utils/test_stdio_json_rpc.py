"""Tests for shared Content-Length JSON framing."""

from __future__ import annotations

from backend.utils.http.stdio_json_rpc import parse_content_length_json_messages


def test_parse_single_message() -> None:
    body = '{"jsonrpc":"2.0","id":1}'
    blob = f'Content-Length: {len(body.encode("utf-8"))}\r\n\r\n{body}'
    out = parse_content_length_json_messages(blob)
    assert len(out) == 1
    assert out[0]['jsonrpc'] == '2.0'
    assert out[0]['id'] == 1


def test_parse_two_messages() -> None:
    m1 = '{"a":1}'
    m2 = '{"b":2}'
    blob = (
        f'Content-Length: {len(m1.encode("utf-8"))}\r\n\r\n{m1}'
        f'Content-Length: {len(m2.encode("utf-8"))}\r\n\r\n{m2}'
    )
    out = parse_content_length_json_messages(blob)
    assert out == [{'a': 1}, {'b': 2}]


def test_parse_skips_non_content_length_noise() -> None:
    body = '{"x":true}'
    blob = f'noise Content-Length: {len(body.encode("utf-8"))}\r\n\r\n{body}'
    out = parse_content_length_json_messages(blob)
    assert out == [{'x': True}]
