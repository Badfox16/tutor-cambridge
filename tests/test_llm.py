import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fakes import fake_ollama  # noqa: E402
from tutor.llm import LLMResult, OllamaProvider  # noqa: E402


class TestOllamaMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = fake_ollama.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_stream_metrics_converted_from_ns(self):
        provider = OllamaProvider(model="fake-model", base_url=self.base)
        result = provider.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "Hello world")
        self.assertEqual(result.thinking_chars, 0)
        self.assertEqual(result.finish_reason, "stop")
        # durations arrive in nanoseconds; must be ms in the result
        self.assertAlmostEqual(result.load_ms, 200.0, places=1)
        self.assertAlmostEqual(result.prefill_ms, 300.0, places=1)
        self.assertAlmostEqual(result.gen_ms, 800.0, places=1)
        self.assertEqual(result.prompt_tokens, 100)
        self.assertEqual(result.gen_tokens, 40)
        self.assertAlmostEqual(result.tokens_per_s, 40 / 0.8, places=1)
        self.assertIsNotNone(result.ttft_ms)
        self.assertLess(result.ttft_ms, result.total_ms)

    def test_thinking_counted_not_shown(self):
        provider = OllamaProvider(model="fake-model", base_url=self.base)
        result = provider.chat([{"role": "user", "content": "hi"}], think=True, stream=False)
        self.assertEqual(result.text, "Hello world")
        self.assertEqual(result.thinking_chars, len("chain of thought"))
        self.assertNotIn("chain of thought", result.text)

    def test_result_as_dict_has_units(self):
        provider = OllamaProvider(model="fake-model", base_url=self.base)
        d = provider.chat([{"role": "user", "content": "hi"}], stream=False).as_dict()
        for key in ("text", "thinking_chars", "finish_reason", "total_ms", "load_ms",
                    "prompt_tokens", "prefill_ms", "gen_tokens", "gen_ms", "tokens_per_s", "ttft_ms"):
            self.assertIn(key, d)

    def test_connection_refused_is_transient(self):
        from tutor.llm import LLMError
        provider = OllamaProvider(model="fake-model", base_url="http://127.0.0.1:1")
        with self.assertRaises(LLMError) as ctx:
            provider.chat([{"role": "user", "content": "hi"}], stream=False)
        self.assertTrue(ctx.exception.transient)


class TestLLMResultDefaults(unittest.TestCase):
    def test_default(self):
        r = LLMResult()
        self.assertEqual(r.text, "")
        self.assertEqual(r.finish_reason, "")
        self.assertIsNone(r.ttft_ms)


if __name__ == "__main__":
    unittest.main()
