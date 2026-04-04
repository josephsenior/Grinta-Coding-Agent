from unittest.mock import MagicMock, patch

from backend.utils.blast_radius import check_blast_radius, check_blast_radius_from_code


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
