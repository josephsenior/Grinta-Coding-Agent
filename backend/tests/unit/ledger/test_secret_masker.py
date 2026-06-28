"""Regression and unit tests for backend.ledger.infra.secret_masker."""

from __future__ import annotations

from backend.ledger.infra.secret_masker import SecretMasker


def test_masks_configured_secret_in_string() -> None:
    m = SecretMasker()
    m.set_secrets({'K': 'sk-secret-token'})
    out = m.replace_secrets(
        {'text': 'prefix sk-secret-token suffix'}, is_top_level=False
    )
    assert out['text'] == 'prefix <secret_hidden> suffix'


def test_top_level_id_field_not_recursed_so_unchanged() -> None:
    """Protected top-level keys are skipped entirely (event envelope)."""
    m = SecretMasker()
    m.set_secrets({'K': 'sk-xyz'})
    data = {'id': 'sk-xyz', 'extra': 'sk-xyz tail'}
    out = m.replace_secrets(data, is_top_level=True)
    assert out['id'] == 'sk-xyz'
    assert out['extra'] == '<secret_hidden> tail'


class TestSecretMaskerInit:
    def test_empty_secrets(self):
        m = SecretMasker()
        assert m.secrets == {}
        assert m._secret_pattern is None
        assert m._secret_bytes == []


class TestSetSecrets:
    def test_set_secrets(self):
        m = SecretMasker()
        m.set_secrets({'API_KEY': 'sk-abc123'})
        assert m.secrets == {'API_KEY': 'sk-abc123'}
        assert m._secret_pattern is not None

    def test_set_secrets_copies(self):
        m = SecretMasker()
        original = {'K': 'V'}
        m.set_secrets(original)
        original['K2'] = 'V2'
        assert 'K2' not in m.secrets

    def test_set_secrets_replaces(self):
        m = SecretMasker()
        m.set_secrets({'A': '1'})
        m.set_secrets({'B': '2'})
        assert m.secrets == {'B': '2'}


class TestUpdateSecrets:
    def test_merge(self):
        m = SecretMasker()
        m.set_secrets({'A': '1'})
        m.update_secrets({'B': '2'})
        assert m.secrets == {'A': '1', 'B': '2'}

    def test_overwrites(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'old'})
        m.update_secrets({'KEY': 'new'})
        assert m.secrets['KEY'] == 'new'


class TestMaskString:
    def test_masks_secret_in_string(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'secret_value'})
        result = m._mask_string('my secret_value here')
        assert 'secret_value' not in result
        assert SecretMasker.PLACEHOLDER in result

    def test_no_secrets_returns_original(self):
        m = SecretMasker()
        assert m._mask_string('no secrets') == 'no secrets'

    def test_empty_string(self):
        m = SecretMasker()
        m.set_secrets({'K': 'V'})
        assert m._mask_string('') == ''

    def test_case_insensitive(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'MySecret'})
        result = m._mask_string('MYSECRET and mysecret')
        assert 'MySecret' not in result.lower()
        assert result.count(SecretMasker.PLACEHOLDER) == 2

    def test_repeated_secret_in_string(self):
        m = SecretMasker()
        m.set_secrets({'API_KEY': 'sk-abc123'})
        result = m.replace_secrets({'content': 'sk-abc123 and sk-abc123 again'})
        assert result['content'].count(SecretMasker.PLACEHOLDER) == 2


class TestMaskBytes:
    def test_masks_bytes(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'tokenabc'})
        result = m._mask_bytes(b'header: tokenabc')
        assert b'tokenabc' not in result
        assert SecretMasker.PLACEHOLDER.encode() in result

    def test_no_secrets_returns_original(self):
        m = SecretMasker()
        result = m._mask_bytes(b'data')
        assert result == b'data'

    def test_empty_bytes(self):
        m = SecretMasker()
        m.set_secrets({'K': 'V'})
        assert m._mask_bytes(b'') == b''


class TestReplaceSecrets:
    def test_top_level_protected_fields(self):
        """Protected fields at top level should not be masked."""
        m = SecretMasker()
        m.set_secrets({'KEY': 'sk123'})
        data = {
            'id': 'evt_sk123',
            'timestamp': '2024-sk123',
            'source': 'sk123_src',
            'message': 'has sk123',
            'content': 'also sk123',
        }
        result = m.replace_secrets(data)
        assert result['id'] == 'evt_sk123'
        assert result['timestamp'] == '2024-sk123'
        assert result['source'] == 'sk123_src'
        assert result['message'] == 'has sk123'
        assert 'sk123' not in result['content']

    def test_all_protected_fields_not_masked_at_top_level(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'secret123'})
        for field in SecretMasker.TOP_LEVEL_PROTECTED_FIELDS:
            data = {field: 'contains secret123', 'other': 'also secret123'}
            result = m.replace_secrets(data)
            assert 'secret123' in result[field], f'Field {field} was masked'
            assert 'secret123' not in result['other']

    def test_nested_not_protected(self):
        """Fields in nested dicts should always be masked."""
        m = SecretMasker()
        m.set_secrets({'KEY': 'mytoken123'})
        data = {
            'nested': {
                'id': 'has mytoken123',
                'message': 'has mytoken123 too',
            }
        }
        result = m.replace_secrets(data)
        assert 'mytoken123' not in result['nested']['id']
        assert 'mytoken123' not in result['nested']['message']

    def test_protected_fields_masked_when_nested(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'secret123'})
        data = {
            'nested': {
                'timestamp': 'secret123 in nested timestamp',
                'message': 'secret123 in nested message',
            }
        }
        result = m.replace_secrets(data)
        assert 'secret123' not in result['nested']['timestamp']
        assert 'secret123' not in result['nested']['message']

    def test_list_values(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'tok'})
        data = {'items': ['tok is here', 'no match']}
        result = m.replace_secrets(data)
        assert 'tok' not in result['items'][0]
        assert result['items'][1] == 'no match'

    def test_tuple_values(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'abc'})
        data = {'vals': ('abc_1', 'abc_2')}
        result = m.replace_secrets(data)
        assert isinstance(result['vals'], tuple)
        assert 'abc' not in result['vals'][0]
        assert 'abc' not in result['vals'][1]

    def test_bytes_values(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'binsecret'})
        data = {'payload': b'data binsecret end'}
        result = m.replace_secrets(data)
        assert b'binsecret' not in result['payload']

    def test_non_string_value_passthrough(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'x'})
        data = {'count': 42, 'flag': True, 'empty': None}
        result = m.replace_secrets(data)
        assert result['count'] == 42
        assert result['flag'] is True
        assert result['empty'] is None

    def test_multiple_secrets(self):
        m = SecretMasker()
        m.set_secrets({'A': 'alpha', 'B': 'beta'})
        data = {'text': 'alpha and beta are secrets'}
        result = m.replace_secrets(data)
        assert 'alpha' not in result['text']
        assert 'beta' not in result['text']

    def test_empty_secret_value_ignored(self):
        m = SecretMasker()
        m.set_secrets({'EMPTY': '', 'REAL': 'real_secret'})
        data = {'text': 'has real_secret'}
        result = m.replace_secrets(data)
        assert 'real_secret' not in result['text']

    def test_deeply_nested(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'secret123'})
        data = {'level1': {'level2': {'level3': [{'level4': 'deep secret123 value'}]}}}
        result = m.replace_secrets(data)
        deep_val = result['level1']['level2']['level3'][0]['level4']
        assert 'secret123' not in deep_val

    def test_empty_data_dict(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'secret'})
        assert m.replace_secrets({}) == {}

    def test_no_secrets_no_masking(self):
        m = SecretMasker()
        data = {'content': 'safe text with no secrets'}
        result = m.replace_secrets(data)
        assert result['content'] == 'safe text with no secrets'


class TestRebuildCache:
    def test_empty_secrets_clears_pattern(self):
        m = SecretMasker()
        m.set_secrets({'K': 'V'})
        m.set_secrets({})
        assert m._secret_pattern is None
        assert m._secret_bytes == []

    def test_longer_secrets_matched_first(self):
        """Longer secrets should be matched before shorter substrings."""
        m = SecretMasker()
        m.set_secrets({'SHORT': 'abc', 'LONG': 'abcdef'})
        result = m._mask_string('prefix abcdef suffix')
        assert result.count(SecretMasker.PLACEHOLDER) >= 1
        assert 'abcdef' not in result

    def test_set_secrets_clears_previous(self):
        m = SecretMasker()
        m.set_secrets({'OLD': 'old_secret'})
        m.set_secrets({'NEW': 'new_secret'})
        result = m.replace_secrets({'content': 'old_secret and new_secret'})
        assert 'old_secret' in result['content']
        assert 'new_secret' not in result['content']

    def test_special_regex_chars_in_secrets(self):
        m = SecretMasker()
        m.set_secrets({'KEY': 'my.secret+value[0]'})
        result = m.replace_secrets({'content': 'has my.secret+value[0] in it'})
        assert 'my.secret+value[0]' not in result['content']
        assert SecretMasker.PLACEHOLDER in result['content']


class TestPlaceholder:
    def test_placeholder_constant(self):
        assert SecretMasker.PLACEHOLDER == '<secret_hidden>'
