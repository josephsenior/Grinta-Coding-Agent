from unittest.mock import MagicMock, patch

from backend.utils.impact_analysis import (
    _grep_fallback_locations,
    _is_test_file,
    analyze_symbol_impact,
)


class TestImpactAnalysis:
    def test_is_test_file_variants(self) -> None:
        assert _is_test_file('backend/tests/unit/test_main.py') is True
        assert _is_test_file('tests/explore/helper.py') is True
        assert _is_test_file('src/test_utils.py') is True
        assert _is_test_file('src/utils_test.py') is True
        assert _is_test_file('backend/specs/my_spec.py') is True
        assert _is_test_file('backend/core/main.py') is False
        assert _is_test_file('src/utils.py') is False

    @patch('backend.utils.impact_analysis.os.path.exists', return_value=True)
    @patch('backend.utils.impact_analysis.get_lsp_client')
    @patch('backend.utils.impact_analysis.TreeSitterEditor.find_symbol')
    def test_analyze_symbol_impact_lsp(
        self, mock_find_symbol, mock_get_lsp_client, mock_exists
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()

        # Mock 10 references (5 production, 5 tests)
        mock_locations = []
        for i in range(5):
            mock_locations.append(
                MagicMock(
                    file=f'src/prod_{i}.py', line=10, column=5, message=f'use_{i}'
                )
            )
            mock_locations.append(
                MagicMock(
                    file=f'tests/test_{i}.py', line=15, column=5, message=f'test_{i}'
                )
            )

        mock_result.locations = mock_locations
        mock_client.query.return_value = mock_result
        mock_find_symbol.return_value = MagicMock(line_start=1)

        report = analyze_symbol_impact('src/define.py', 'my_func')

        assert report is not None
        assert report.symbol == 'my_func'
        assert report.engine == 'lsp'
        assert report.confidence == 'high'
        assert report.total_references == 10
        assert report.production_references == 5
        assert report.test_references == 5
        assert report.unique_files == 10
        # crosses package since definition is in src/ but references are src/prod_X.py and tests/test_X.py
        assert report.risk == 'high'
        assert 'Referenced outside its defining package' in report.reasons

    @patch('backend.utils.impact_analysis.os.path.exists', return_value=True)
    @patch('backend.utils.impact_analysis.subprocess.run')
    @patch('backend.utils.impact_analysis.shutil.which', return_value='rg')
    @patch('backend.utils.impact_analysis.get_lsp_client')
    @patch('backend.utils.impact_analysis.TreeSitterEditor.find_symbol')
    def test_analyze_symbol_impact_ripgrep_fallback(
        self,
        mock_find_symbol,
        mock_get_lsp_client,
        mock_shutil_which,
        mock_run,
        mock_exists,
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = False
        mock_get_lsp_client.return_value = mock_client

        mock_find_symbol.return_value = MagicMock(line_start=1)
        mock_run.return_value = MagicMock(
            stdout='src/prod_1.py:10:result = my_func()\nsrc/prod_2.py:12:my_func()\n'
        )

        report = analyze_symbol_impact('src/define.py', 'my_func')

        assert report is not None
        assert report.symbol == 'my_func'
        assert report.engine == 'ripgrep'
        assert report.confidence == 'medium'
        assert report.total_references == 2
        assert report.unique_files == 2
        assert report.risk == 'medium'

    @patch('backend.utils.impact_analysis.subprocess.run')
    @patch('backend.utils.impact_analysis.shutil.which', return_value='rg')
    def test_grep_fallback_locations_with_rg(self, mock_which, mock_run) -> None:
        mock_run.return_value = MagicMock(
            stdout='src/file1.py:5:value = symbol\nsrc/file2.py:10:symbol()\n'
        )
        locs = _grep_fallback_locations('symbol', 'src/define.py', 1, search_root='.')
        assert len(locs) == 2
        assert locs[0].file_path == 'src/file1.py'
        assert locs[0].line == 5
        assert locs[1].file_path == 'src/file2.py'
        assert locs[1].line == 10
