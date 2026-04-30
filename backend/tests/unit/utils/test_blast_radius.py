from unittest.mock import MagicMock, patch

from backend.utils.blast_radius import (
    _grep_cross_file_refs,
    check_blast_radius,
    check_blast_radius_from_code,
)


class TestBlastRadiusHook:
    @patch('backend.utils.blast_radius.get_lsp_client')
    @patch('backend.utils.blast_radius.TreeSitterEditor.find_symbol')
    def test_blast_radius_exceeds_threshold(
        self, mock_find_symbol, mock_get_lsp_client
    ):
        mock_client = MagicMock()
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()
        mock_result.locations = [MagicMock()] * 15
        mock_client.query.return_value = mock_result
        mock_find_symbol.return_value = MagicMock(line_start=1)

        result_message = check_blast_radius('file.py', 'greet', threshold=10)

        assert result_message is not None
        assert 'BLAST RADIUS EXCEEDS' in result_message
        assert '15 other locations' in result_message

    @patch('backend.utils.blast_radius.get_lsp_client')
    @patch('backend.utils.blast_radius.TreeSitterEditor.find_symbol')
    def test_blast_radius_under_threshold(self, mock_find_symbol, mock_get_lsp_client):
        mock_client = MagicMock()
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()
        mock_result.locations = [MagicMock()] * 5
        mock_client.query.return_value = mock_result
        mock_find_symbol.return_value = MagicMock(line_start=1)

        result_message = check_blast_radius('file.py', 'greet', threshold=10)

        assert result_message is None

    @patch('backend.utils.blast_radius.get_lsp_client')
    @patch('backend.utils.blast_radius.TreeSitterEditor.find_symbol')
    def test_blast_radius_from_code_snippet(
        self, mock_find_symbol, mock_get_lsp_client
    ):
        mock_client = MagicMock()
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()
        mock_result.locations = [MagicMock()] * 12
        mock_client.query.return_value = mock_result
        mock_find_symbol.return_value = MagicMock(line_start=1)

        snippet = 'def add(a, b):\n    return a + b'
        result_message = check_blast_radius_from_code('file.py', snippet, threshold=10)

        assert result_message is not None
        assert 'BLAST RADIUS EXCEEDS' in result_message
        assert 'add' in result_message

    @patch('backend.utils.blast_radius.subprocess.run')
    @patch('backend.utils.blast_radius.shutil.which', return_value='rg')
    def test_grep_cross_file_refs_with_rg(self, _mock_which, mock_run):
        mock_run.return_value = MagicMock(stdout='a.py:2\nb.py:3\n')
        assert _grep_cross_file_refs('symbol', search_root='/tmp') == 5

    @patch('backend.utils.blast_radius.subprocess.run')
    @patch('backend.utils.blast_radius.shutil.which', return_value=None)
    def test_grep_cross_file_refs_with_grep_fallback(self, _mock_which, mock_run):
        mock_run.return_value = MagicMock(stdout='a.py:1\nb.py:4\n')
        assert _grep_cross_file_refs('symbol', search_root='/tmp') == 5

    @patch(
        'backend.utils.blast_radius.subprocess.run', side_effect=RuntimeError('boom')
    )
    def test_grep_cross_file_refs_handles_subprocess_error(self, _mock_run):
        assert _grep_cross_file_refs('symbol', search_root='/tmp') == 0

    @patch('backend.utils.blast_radius._grep_cross_file_refs', return_value=17)
    @patch('backend.utils.blast_radius.get_lsp_client')
    @patch('backend.utils.blast_radius.TreeSitterEditor.find_symbol')
    def test_check_blast_radius_uses_grep_fallback_when_lsp_refs_empty(
        self, mock_find_symbol, mock_get_lsp_client, _mock_grep
    ):
        mock_client = MagicMock()
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()
        mock_result.locations = []
        mock_client.query.return_value = mock_result
        mock_find_symbol.return_value = MagicMock(line_start=1)

        result_message = check_blast_radius('file.py', 'greet', threshold=10)
        assert result_message is not None
        assert '~17' in result_message

    @patch('backend.utils.blast_radius.TreeSitterEditor.find_symbol', return_value=None)
    def test_check_blast_radius_returns_none_when_symbol_not_found(self, _mock_find):
        assert check_blast_radius('file.py', 'unknown', threshold=1) is None
