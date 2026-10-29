"""Browser OAuth and protected renewable credentials for ChatGPT plan usage."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
TOKEN_URL = ISSUER + '/api/accounts/oauth/token'
SERVICE = 'grinta-chatgpt-plan'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'


class PlanAuthError(RuntimeError):
    """Authorization requires user action; secret HTTP responses are not logged."""


def _store():
    import keyring

    backend = keyring.get_keyring()
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring

        if not isinstance(backend, WinVaultKeyring):
            raise PlanAuthError(
                'Windows Credential Manager is required for saved sign-in.'
            )
    elif 'plaintext' in type(backend).__name__.lower() or backend.priority <= 0:
        raise PlanAuthError('A protected OS credential store is required.')
    return keyring


def _load(profile):
    value = _store().get_password(SERVICE, profile)
    return json.loads(value) if value else None


def _save(profile, value):
    _store().set_password(SERVICE, profile, json.dumps(value))


def _lock():
    from filelock import FileLock

    folder = Path.home() / '.grinta' / 'chatgpt-plan'
    folder.mkdir(parents=True, exist_ok=True)
    return FileLock(str(folder / 'credentials.lock'), timeout=30)


def _exchange(data):
    try:
        response = httpx.post(
            TOKEN_URL, data={**data, 'resource': RESOURCE}, timeout=30
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise PlanAuthError(
            'ChatGPT authorization failed; run sign-in again.'
        ) from None


def _identity(token, client_id, nonce=None):
    import jwt

    try:
        discovery = httpx.get(ISSUER + '/.well-known/openid-configuration', timeout=30)
        discovery.raise_for_status()
        uri = discovery.json()['jwks_uri']
        if (
            urlparse(uri).scheme != 'https'
            or urlparse(uri).hostname != 'auth.openai.com'
        ):
            raise ValueError('unexpected signing-key endpoint')
        key = jwt.PyJWKClient(uri, timeout=30).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=['RS256'],
            audience=client_id,
            issuer=ISSUER,
            options={'require': ['exp', 'iss', 'sub', 'aud']},
        )
        if nonce is not None and not secrets.compare_digest(
            str(claims.get('nonce', '')), nonce
        ):
            raise ValueError('invalid nonce')
        return claims
    except (jwt.PyJWTError, ValueError, KeyError, httpx.HTTPError):
        raise PlanAuthError('ChatGPT identity validation failed.') from None


def _merge_tokens(previous, tokens):
    scopes = tokens.get('scope')
    granted = scopes.split() if isinstance(scopes, str) else previous.get('scopes', [])
    if 'chatgpt.tokens.use.direct' not in granted or not tokens.get('access_token'):
        raise PlanAuthError('ChatGPT plan usage permission was not granted.')
    if str(tokens.get('token_type', 'Bearer')).lower() != 'bearer':
        raise PlanAuthError('Unsupported authorization token type.')
    return {
        **previous,
        **{
            k: tokens[k]
            for k in ('access_token', 'refresh_token', 'id_token')
            if tokens.get(k)
        },
        'scopes': granted,
        'expires_at': time.time() + float(tokens['expires_in']),
    }


def access_token(profile='default'):
    """Serialize refresh across processes and persist rotated tokens together."""
    with _lock():
        record = _load(profile)
        if not record or not record.get('access_token'):
            raise PlanAuthError(
                'Run python -m backend.inference.clients.chatgpt_plan_auth login first.'
            )
        if 'chatgpt.tokens.use.direct' not in record.get('scopes', []):
            raise PlanAuthError(
                'ChatGPT plan usage permission is missing; sign in again.'
            )
        if record.get('expires_at', 0) <= time.time() + 60:
            if not record.get('refresh_token'):
                raise PlanAuthError('Renewable session unavailable; sign in again.')
            tokens = _exchange(
                {
                    'grant_type': 'refresh_token',
                    'client_id': record['client_id'],
                    'refresh_token': record['refresh_token'],
                }
            )
            if tokens.get('id_token'):
                identity = _identity(tokens['id_token'], record['client_id'])
                if identity['sub'] != record['subject']:
                    raise PlanAuthError(
                        'Renewed identity differs from the selected account.'
                    )
            record = _merge_tokens(record, tokens)
            _save(profile, record)
        return record['access_token']


def _callback(query, state, registered_client):
    if not secrets.compare_digest(query.get('state', [''])[0], state):
        raise PlanAuthError('Invalid sign-in state.')
    if query.get('error'):
        raise PlanAuthError('ChatGPT sign-in was declined or failed.')
    client = query.get('client_id', [registered_client or ''])[0]
    if (
        not client
        or client == 'dynamic_agent_client'
        or (registered_client and client != registered_client)
    ):
        raise PlanAuthError('Sign-in returned an invalid client registration.')
    code = query.get('code', [''])[0]
    if not code:
        raise PlanAuthError('Sign-in did not return an authorization code.')
    return code, client


def login(profile='default', timeout=300):
    with _lock():
        previous = _load(profile) or {}
        host = _load('__host__') or {'id': 'urn:uuid:' + str(uuid.uuid4())}
        _save('__host__', host)
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != '/auth/callback':
                self.send_error(404)
                return
            try:
                result['value'] = _callback(
                    parse_qs(parsed.query), state, previous.get('client_id')
                )
            except PlanAuthError:
                self.send_error(400, 'Sign-in callback rejected')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Return to Grinta to finish sign-in.')

    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        redirect = f'http://127.0.0.1:{server.server_port}/auth/callback'
        params = {
            'client_id': previous.get('client_id', 'dynamic_agent_client'),
            'ext_agent_host_id': host['id'],
            'response_type': 'code',
            'redirect_uri': redirect,
            'scope': SCOPE,
            'resource': RESOURCE,
            'state': state,
            'nonce': nonce,
            'code_challenge_method': 'S256',
            'code_challenge': base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .decode()
            .rstrip('='),
        }
        if previous.get('client_id'):
            if previous.get('id_token'):
                params['id_token_hint'] = previous['id_token']
        else:
            params['agent_name_hint'] = 'Grinta'
        if not webbrowser.open(ISSUER + '/api/accounts/authorize?' + urlencode(params)):
            raise PlanAuthError('Could not open the system browser.')
        deadline = time.monotonic() + timeout
        while 'value' not in result:
            if time.monotonic() >= deadline:
                raise PlanAuthError('Browser sign-in timed out.')
            server.timeout = min(1, deadline - time.monotonic())
            server.handle_request()
    code, client_id = result['value']
    with _lock():
        # Retain the issued registration even if exchange fails or the code expires.
        if (_load(profile) or {}) != previous:
            raise PlanAuthError('Account changed during sign-in; start sign-in again.')
        pending = {**previous, 'client_id': client_id}
        _save(profile, pending)
        tokens = _exchange(
            {
                'grant_type': 'authorization_code',
                'client_id': client_id,
                'code': code,
                'code_verifier': verifier,
                'redirect_uri': redirect,
            }
        )
        identity = _identity(tokens.get('id_token', ''), client_id, nonce)
        if previous.get('subject') and previous['subject'] != identity['sub']:
            raise PlanAuthError('Selected account changed; use a new profile instead.')
        record = _merge_tokens(
            {**pending, 'subject': identity['sub'], 'email': identity.get('email', '')},
            tokens,
        )
        _save(profile, record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['login', 'status', 'models'])
    parser.add_argument('--profile', default='default')
    args = parser.parse_args()
    try:
        if args.command == 'login':
            login(args.profile)
            print('ChatGPT plan sign-in completed.')
        elif args.command == 'models':
            token = access_token(args.profile)
            try:
                response = httpx.get(
                    RESOURCE + '/models',
                    headers={'Authorization': 'Bearer ' + token},
                    timeout=30,
                )
                response.raise_for_status()
                for model in response.json()['models']:
                    if model.get('visibility') == 'list':
                        print(model['slug'])
            except (httpx.HTTPError, ValueError, KeyError):
                raise PlanAuthError(
                    'Could not list models for this ChatGPT connection.'
                ) from None
        else:
            with _lock():
                record = _load(args.profile) or {}
            print('Connected' if record.get('access_token') else 'Not signed in')
    except PlanAuthError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
