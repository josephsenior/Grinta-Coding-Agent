"""Authorization boundaries and renewable sessions without a real account."""

from contextlib import nullcontext

import pytest

from backend.inference.clients import chatgpt_plan_auth as auth


@pytest.mark.parametrize(
    'query',
    [
        {'state': ['wrong'], 'code': ['x'], 'client_id': ['issued']},
        {'state': ['s'], 'error': ['access_denied']},
        {'state': ['s'], 'code': ['x'], 'client_id': ['dynamic_agent_client']},
        {'state': ['s'], 'code': ['x'], 'client_id': ['different']},
    ],
)
def test_callback_rejects_unbound_or_declined_registration(query):
    with pytest.raises(auth.PlanAuthError):
        auth._callback(query, 's', 'issued')


def test_returning_registration_can_omit_client_id():
    assert auth._callback({'state': ['s'], 'code': ['code']}, 's', 'issued') == (
        'code',
        'issued',
    )


def test_refresh_rotates_tokens_and_preserves_grant(monkeypatch):
    record = {
        'client_id': 'issued',
        'subject': 'subject',
        'access_token': 'old',
        'refresh_token': 'r1',
        'expires_at': 0,
        'scopes': ['chatgpt.tokens.use.direct'],
    }
    saved = []
    monkeypatch.setattr(auth, '_lock', lambda: nullcontext())
    monkeypatch.setattr(auth, '_load', lambda profile: dict(record))
    monkeypatch.setattr(auth, '_save', lambda profile, value: saved.append(value))

    def exchange(data):
        assert data == {
            'grant_type': 'refresh_token',
            'client_id': 'issued',
            'refresh_token': 'r1',
        }
        return {'access_token': 'new', 'refresh_token': 'r2', 'expires_in': 3600}

    monkeypatch.setattr(auth, '_exchange', exchange)
    assert auth.access_token() == 'new'
    assert saved[0]['refresh_token'] == 'r2'
    assert saved[0]['scopes'] == record['scopes']


def test_missing_usage_permission_rejected():
    with pytest.raises(auth.PlanAuthError, match='permission'):
        auth._merge_tokens(
            {}, {'access_token': 'token', 'expires_in': 3600, 'scope': 'openid'}
        )


def test_valid_access_does_not_refresh(monkeypatch):
    monkeypatch.setattr(auth, '_lock', lambda: nullcontext())
    monkeypatch.setattr(
        auth,
        '_load',
        lambda profile: {
            'access_token': 'valid',
            'expires_at': auth.time.time() + 3600,
            'scopes': ['chatgpt.tokens.use.direct'],
        },
    )
    monkeypatch.setattr(
        auth, '_exchange', lambda data: pytest.fail('unexpected refresh')
    )
    assert auth.access_token() == 'valid'


@pytest.mark.parametrize(
    'nonce,audience,accepted',
    [('n', 'issued', True), ('wrong', 'issued', False), ('n', 'other', False)],
)
def test_signed_identity_is_bound_to_client_and_nonce(
    monkeypatch, nonce, audience, accepted
):
    from types import SimpleNamespace

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = jwt.encode(
        {
            'sub': 'account',
            'iss': auth.ISSUER,
            'aud': audience,
            'exp': int(auth.time.time()) + 300,
            'nonce': nonce,
        },
        private,
        algorithm='RS256',
    )
    discovery = SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'jwks_uri': auth.ISSUER + '/jwks'}
    )
    monkeypatch.setattr(auth.httpx, 'get', lambda *a, **k: discovery)
    monkeypatch.setattr(
        jwt.PyJWKClient,
        'get_signing_key_from_jwt',
        lambda *a: SimpleNamespace(key=private.public_key()),
    )
    if accepted:
        assert auth._identity(encoded, 'issued', 'n')['sub'] == 'account'
    else:
        with pytest.raises(auth.PlanAuthError, match='validation'):
            auth._identity(encoded, 'issued', 'n')
