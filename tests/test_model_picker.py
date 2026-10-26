"""Filtering, highlighting and the cached-then-live model lists behind the model picker."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from crucible import model_picker
from crucible.model_picker import _Catalog, _highlighted, filter_models, match, score


def _provider(catalog):
    return type("P", (), {"catalog": staticmethod(catalog)})


def _offline():
    raise OSError("down")


class TestFilter(unittest.TestCase):
    ITEMS = [("openrouter/moonshotai/kimi-k2.6", ""), ("openrouter/qwen/qwen3.5-9b", ""),
             ("ollama/qwen3.5:9b-mlx", ""), ("lmstudio/google/gemma-3-12b", "")]

    def values(self, query):
        return [v for v, _, _ in filter_models(query, self.ITEMS)]

    def test_empty_query_keeps_order(self):
        self.assertEqual(self.values(""), [v for v, _ in self.ITEMS])

    def test_every_word_must_match(self):
        self.assertEqual(self.values("qwen ollama"), ["ollama/qwen3.5:9b-mlx"])

    def test_subsequence_match(self):
        self.assertEqual(self.values("kk26"), ["openrouter/moonshotai/kimi-k2.6"])

    def test_boundary_substring_beats_subsequence(self):
        self.assertGreater(score("gem", "lmstudio/google/gemma-3-12b"), score("gma", "lmstudio/google/gemma-3-12b"))

    def test_prefers_substring_at_a_boundary(self):
        # 'qwen' appears twice; the match at the '/' boundary after 'openrouter' wins
        _, hits = match("qwen", "openrouter/qwen/qwen3.5-9b")
        self.assertEqual(hits, {11, 12, 13, 14})

    def test_positions_for_highlighting(self):
        _, hits = match("kk26", "kimi-k2.6")
        self.assertEqual(hits, {0, 5, 6, 8})
        self.assertEqual(_highlighted("kimi", {0}, "", "hit"), [("hit", "k"), ("", "imi")])

    def test_no_match(self):
        self.assertIsNone(score("zzz", "ollama/llama3"))


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.dict(os.environ, {"XDG_CACHE_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def catalog(self, fake, names, pinned=()):
        with patch.dict(model_picker.providers.PROVIDERS, fake, clear=True):
            cat = _Catalog(names, list(pinned))
            cat.wait()
        return cat

    def test_offline_provider_and_pinned_first(self):
        cat = self.catalog({"ollama": _provider(_offline),
                            "lmstudio": _provider(lambda: [("a", "loaded"), ("b", "")])},
                           ["ollama", "lmstudio"], pinned=[("lmstudio/b", "run before")])
        self.assertEqual(cat.items(), [("lmstudio/b", "run before"), ("lmstudio/a", "loaded")])
        self.assertIn("ollama: offline", cat.summary())

    def test_fetched_lists_are_cached_and_shown_before_the_refresh(self):
        self.catalog({"lmstudio": _provider(lambda: [("a", "loaded")])}, ["lmstudio"])
        saved = json.loads(model_picker.cache_file().read_text())
        self.assertEqual(saved["lmstudio"]["models"], [["a", "loaded"]])

        release = model_picker.threading.Event()

        def slow():
            release.wait(5)
            return [("b", "")]
        with patch.dict(model_picker.providers.PROVIDERS, {"lmstudio": _provider(slow)}, clear=True):
            cat = _Catalog(["lmstudio"], [])
            self.assertEqual(cat.items(), [("lmstudio/a", "loaded")])   # from the cache, at once
            self.assertIn("refreshing", cat.summary())
            release.set()
            cat.wait()
        self.assertEqual(cat.items(), [("lmstudio/b", "")])

    def test_offline_provider_drops_its_cached_models(self):
        self.catalog({"lmstudio": _provider(lambda: [("a", "")])}, ["lmstudio"])
        cat = self.catalog({"lmstudio": _provider(_offline)}, ["lmstudio"])
        self.assertEqual(cat.items(), [])

    def test_unwritable_cache_is_ignored(self):
        with patch.object(model_picker, "cache_file", return_value=model_picker.Path("/nonexistent/x/models.json")):
            cat = self.catalog({"lmstudio": _provider(lambda: [("a", "")])}, ["lmstudio"])
        self.assertEqual(cat.items(), [("lmstudio/a", "")])


if __name__ == "__main__":
    unittest.main()
