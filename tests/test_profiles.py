import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tutor import config  # noqa: E402

TOML = """
[default]
model = "m1"
prompt = "marker-compact"
think = "off"
temperature = 0.2
num_ctx = 8192
max_tokens = 1024
keep_alive = "10m"
repeats = 1
limit = 0
note_ignored = "not a profile key"

[gemma-fast]
model = "gemma4:e4b"

[qwen-thinking]
think = "on"
max_tokens = 2048
"""


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.path = Path(ROOT / "tests" / "fixtures" / "profiles-test.toml")
        self.path.write_text(TOML, encoding="utf-8")

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_default_inherited_by_profiles(self):
        profiles = config.load_profiles(self.path)
        self.assertEqual(profiles["gemma-fast"]["prompt"], "marker-compact")
        self.assertEqual(profiles["gemma-fast"]["model"], "gemma4:e4b")
        self.assertNotIn("note_ignored", profiles["gemma-fast"])

    def test_resolve_profile(self):
        p = config.resolve_profile("qwen-thinking", path=self.path)
        self.assertEqual(p["think"], "on")
        self.assertEqual(p["max_tokens"], 2048)
        self.assertEqual(p["model"], "m1")  # inherited

    def test_cli_overrides_win(self):
        p = config.resolve_profile("gemma-fast",
                                   {"model": "qwen3.5:9b", "limit": 30}, path=self.path)
        self.assertEqual(p["model"], "qwen3.5:9b")
        self.assertEqual(p["limit"], 30)
        self.assertEqual(p["prompt"], "marker-compact")

    def test_none_overrides_ignored(self):
        p = config.resolve_profile("gemma-fast", {"model": None}, path=self.path)
        self.assertEqual(p["model"], "gemma4:e4b")

    def test_unknown_profile_raises(self):
        with self.assertRaises(KeyError):
            config.resolve_profile("nope", path=self.path)

    def test_missing_file_falls_back(self):
        p = config.resolve_profile(None, path=Path("/nonexistent/profiles.toml"))
        self.assertEqual(p["prompt"], "marker-full")  # env/config defaults
        self.assertEqual(p["name"], "default")


class TestProviderInstanceOptions(unittest.TestCase):
    def test_options_come_from_instance(self):
        from tutor.llm import OllamaProvider
        provider = OllamaProvider(model="m", base_url="http://127.0.0.1:1",
                                  temperature=0.7, num_ctx=4096, max_tokens=512)
        # chat() with no explicit options uses the instance's profile values
        result = OllamaProvider(model="m")  # noqa: F841
        self.assertEqual(provider.temperature, 0.7)
        self.assertEqual(provider.num_ctx, 4096)
        self.assertEqual(provider.max_tokens, 512)


if __name__ == "__main__":
    unittest.main()
