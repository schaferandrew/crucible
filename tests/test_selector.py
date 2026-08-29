#!/usr/bin/env python3
"""Unit tests for selector and model resolution with mocked APIs."""
import unittest
from unittest.mock import patch, MagicMock
import json
import sys
from io import StringIO
import importlib

from crucible.selector import select_from_list, _fallback_select
from crucible.runner import resolve_model


class TestSelector(unittest.TestCase):
    """Tests for the interactive selector."""

    @patch('crucible.selector.sys.stdin', new_callable=lambda: StringIO('1\n'))
    @patch('crucible.selector.sys.stderr', new_callable=StringIO)
    def test_fallback_select_first_item(self, mock_stderr, mock_stdin):
        items = ['item1', 'item2', 'item3']
        result = _fallback_select(items, "Select:")
        self.assertEqual(result, 'item1')

    @patch('crucible.selector.sys.stdin', new_callable=lambda: StringIO('2\n'))
    @patch('crucible.selector.sys.stderr', new_callable=StringIO)
    def test_fallback_select_second_item(self, mock_stderr, mock_stdin):
        items = ['item1', 'item2', 'item3']
        result = _fallback_select(items, "Select:")
        self.assertEqual(result, 'item2')

    @patch('crucible.selector.sys.stdin', new_callable=lambda: StringIO('q\n'))
    @patch('crucible.selector.sys.stderr', new_callable=StringIO)
    def test_fallback_select_quit(self, mock_stderr, mock_stdin):
        items = ['item1', 'item2']
        result = _fallback_select(items, "Select:")
        self.assertIsNone(result)

    @patch('crucible.selector.sys.stdin', new_callable=lambda: StringIO('5\n'))
    @patch('crucible.selector.sys.stderr', new_callable=StringIO)
    def test_fallback_select_invalid_index(self, mock_stderr, mock_stdin):
        items = ['item1', 'item2']
        result = _fallback_select(items, "Select:")
        self.assertIsNone(result)

    @patch('crucible.selector.sys.stdin', new_callable=lambda: StringIO('abc\n'))
    @patch('crucible.selector.sys.stderr', new_callable=StringIO)
    def test_fallback_select_non_numeric(self, mock_stderr, mock_stdin):
        items = ['item1', 'item2']
        result = _fallback_select(items, "Select:")
        self.assertIsNone(result)


class TestDirectRunnerModelFetching(unittest.TestCase):
    """Tests for model fetching with mocked HTTP responses."""

    @patch('crucible.direct_runner.urllib.request.urlopen')
    def test_fetch_ollama_models_success(self, mock_urlopen):
        from crucible.direct_runner import fetch_ollama_models
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "models": [
                {"name": "qwen3.5:9b-mlx"},
                {"name": "llama3.1:8b"},
                {"name": "gemma2:2b"}
            ]
        }).encode()
        mock_urlopen.return_value = mock_response

        models = fetch_ollama_models()
        self.assertEqual(models, ['qwen3.5:9b-mlx', 'llama3.1:8b', 'gemma2:2b'])

    @patch('crucible.direct_runner.urllib.request.urlopen')
    def test_fetch_ollama_models_empty(self, mock_urlopen):
        from crucible.direct_runner import fetch_ollama_models
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"models": []}).encode()
        mock_urlopen.return_value = mock_response

        models = fetch_ollama_models()
        self.assertEqual(models, [])

    @patch('crucible.direct_runner.urllib.request.urlopen')
    def test_fetch_ollama_models_error(self, mock_urlopen):
        from crucible.direct_runner import fetch_ollama_models
        mock_urlopen.side_effect = Exception("Connection refused")
        models = fetch_ollama_models()
        self.assertEqual(models, [])

    @patch('crucible.direct_runner.os.environ.get')
    @patch('crucible.direct_runner.urllib.request.urlopen')
    def test_fetch_openrouter_models_success(self, mock_urlopen, mock_env_get):
        from crucible.direct_runner import fetch_openrouter_models
        mock_env_get.return_value = 'test-api-key'
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "data": [
                {"id": "qwen/qwen-2.5-7b-instruct"},
                {"id": "meta-llama/llama-3.1-8b-instruct"},
                {"id": "google/gemma-2-9b-it"}
            ]
        }).encode()
        mock_urlopen.return_value = mock_response

        models = fetch_openrouter_models()
        self.assertEqual(models, [
            'qwen/qwen-2.5-7b-instruct',
            'meta-llama/llama-3.1-8b-instruct',
            'google/gemma-2-9b-it'
        ])

    @patch('crucible.direct_runner.os.environ.get')
    def test_fetch_openrouter_models_no_api_key(self, mock_env_get):
        from crucible.direct_runner import fetch_openrouter_models
        mock_env_get.return_value = None
        models = fetch_openrouter_models()
        self.assertEqual(models, [])

    @patch('crucible.direct_runner.os.environ.get')
    @patch('crucible.direct_runner.urllib.request.urlopen')
    def test_fetch_openrouter_models_error(self, mock_urlopen, mock_env_get):
        from crucible.direct_runner import fetch_openrouter_models
        mock_env_get.return_value = 'test-api-key'
        mock_urlopen.side_effect = Exception("API error")
        models = fetch_openrouter_models()
        self.assertEqual(models, [])


class TestFindModelMatches(unittest.TestCase):
    """Tests for fuzzy model matching across providers."""

    def test_find_model_matches_exact_ollama(self):
        import crucible.direct_runner
        importlib.reload(crucible.direct_runner)
        
        # Patch AFTER reload
        crucible.direct_runner.fetch_ollama_models = MagicMock(return_value=['qwen3.5:9b-mlx', 'llama3.1:8b'])
        crucible.direct_runner.fetch_openrouter_models = MagicMock(return_value=['qwen/qwen-2.5-7b-instruct', 'meta-llama/llama-3.1-8b-instruct'])
        
        from crucible.direct_runner import find_model_matches
        
        matches = find_model_matches('qwen3.5:9b-mlx')
        self.assertEqual(matches, ['ollama/qwen3.5:9b-mlx'])

    def test_find_model_matches_fuzzy_openrouter(self):
        import crucible.direct_runner
        importlib.reload(crucible.direct_runner)
        
        crucible.direct_runner.fetch_ollama_models = MagicMock(return_value=['llama3.1:8b'])
        # The function splits on ':' and ' ' and checks each part
        # 'qwen2.5' -> parts: ['qwen2.5']
        # Need model IDs containing 'qwen2.5' (without dash)
        crucible.direct_runner.fetch_openrouter_models = MagicMock(return_value=['qwen/qwen2.5-7b-instruct', 'qwen/qwen2.5-32b-instruct'])
        
        from crucible.direct_runner import find_model_matches
        
        matches = find_model_matches('qwen2.5')
        self.assertIn('openrouter/qwen/qwen2.5-7b-instruct', matches)
        self.assertIn('openrouter/qwen/qwen2.5-32b-instruct', matches)

    def test_find_model_matches_both_providers(self):
        import crucible.direct_runner
        importlib.reload(crucible.direct_runner)
        
        # Exact match on ollama requires full model name
        crucible.direct_runner.fetch_ollama_models = MagicMock(return_value=['qwen3.5:9b-mlx'])
        # Fuzzy match on openrouter - query 'qwen3.5' contains 'qwen3' and '5' as parts
        # The function splits on ':' and ' ' -> ['qwen3.5'] -> checks if 'qwen3.5' in model
        crucible.direct_runner.fetch_openrouter_models = MagicMock(return_value=['qwen/qwen3.5-9b', 'qwen/qwen-2.5-7b-instruct'])
        
        from crucible.direct_runner import find_model_matches
        
        matches = find_model_matches('qwen3.5:9b-mlx')
        self.assertIn('ollama/qwen3.5:9b-mlx', matches)
        self.assertIn('openrouter/qwen/qwen3.5-9b', matches)

    def test_find_model_matches_none(self):
        import crucible.direct_runner
        importlib.reload(crucible.direct_runner)
        
        crucible.direct_runner.fetch_ollama_models = MagicMock(return_value=['llama3.1:8b'])
        crucible.direct_runner.fetch_openrouter_models = MagicMock(return_value=['meta-llama/llama-3.1-8b-instruct'])
        
        from crucible.direct_runner import find_model_matches
        
        matches = find_model_matches('nonexistent-model')
        self.assertEqual(matches, [])


class TestResolveModel(unittest.TestCase):
    """Tests for the model resolution logic."""

    def test_resolve_provider_and_model(self):
        result = resolve_model('ollama', 'qwen3.5:9b-mlx')
        self.assertEqual(result, 'ollama/qwen3.5:9b-mlx')

    def test_resolve_model_with_prefix(self):
        result = resolve_model(None, 'ollama/qwen3.5:9b-mlx')
        self.assertEqual(result, 'ollama/qwen3.5:9b-mlx')

    def test_resolve_neither(self):
        result = resolve_model(None, None)
        self.assertIsNone(result)

    @patch('crucible.runner.direct_runner.find_model_matches')
    @patch('crucible.runner.select_from_list')
    def test_resolve_model_fuzzy_single_match(self, mock_select, mock_find):
        mock_find.return_value = ['ollama/qwen3.5:9b-mlx']
        mock_select.return_value = 'ollama/qwen3.5:9b-mlx'

        result = resolve_model(None, 'qwen3.5:9b-mlx')
        self.assertEqual(result, 'ollama/qwen3.5:9b-mlx')

    @patch('crucible.runner.direct_runner.find_model_matches')
    @patch('crucible.runner.select_from_list')
    def test_resolve_model_fuzzy_multiple_matches(self, mock_select, mock_find):
        mock_find.return_value = [
            'ollama/qwen3.5:9b-mlx',
            'openrouter/qwen/qwen-3.5-9b'
        ]
        mock_select.return_value = 'ollama/qwen3.5:9b-mlx'

        result = resolve_model(None, 'qwen3.5')
        self.assertEqual(result, 'ollama/qwen3.5:9b-mlx')

    @patch('crucible.runner.direct_runner.find_model_matches')
    def test_resolve_model_fuzzy_no_matches(self, mock_find):
        mock_find.return_value = []
        with self.assertRaises(SystemExit) as cm:
            resolve_model(None, 'nonexistent')
        self.assertEqual(cm.exception.code, 1)

    @patch('crucible.runner.direct_runner.fetch_ollama_models')
    @patch('crucible.runner.select_from_list')
    def test_resolve_provider_only_ollama(self, mock_select, mock_fetch):
        mock_fetch.return_value = ['qwen3.5:9b-mlx', 'llama3.1:8b']
        mock_select.return_value = 'ollama/qwen3.5:9b-mlx'

        result = resolve_model('ollama', None)
        self.assertEqual(result, 'ollama/qwen3.5:9b-mlx')

    @patch('crucible.runner.direct_runner.fetch_openrouter_models')
    @patch('crucible.runner.select_from_list')
    def test_resolve_provider_only_openrouter(self, mock_select, mock_fetch):
        mock_fetch.return_value = ['qwen/qwen-3.5-9b', 'meta-llama/llama-3.1-8b-instruct']
        mock_select.return_value = 'openrouter/qwen/qwen-3.5-9b'

        result = resolve_model('openrouter', None)
        self.assertEqual(result, 'openrouter/qwen/qwen-3.5-9b')

    def test_resolve_unknown_provider(self):
        with self.assertRaises(SystemExit) as cm:
            resolve_model('unknown', None)
        self.assertEqual(cm.exception.code, 1)


if __name__ == '__main__':
    unittest.main()