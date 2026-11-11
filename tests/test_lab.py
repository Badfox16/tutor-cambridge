import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fakes import fake_lab  # noqa: E402
from tutor.lab import LabClient, LabError  # noqa: E402


class TestLabClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = fake_lab.start()
        cls.lab = LabClient(base_url=cls.base, key=fake_lab.KEY)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_full_loop(self):
        version = self.lab.dataset_version()["datasetVersion"]
        run = self.lab.create_run(harness_name="test", model="fake", used_scheme=True,
                                  git_commit="abc123", dirty=True)
        self.assertIn("runId", run)
        run_id = run["runId"]

        answers = self.lab.answers(run_id=run_id)["answers"]
        self.assertTrue(answers)
        a = answers[0]
        question = self.lab.question(a["questionId"], run_id=run_id)
        self.assertNotIn("points", question["lines"][0])  # no scheme in public question
        scheme = self.lab.scheme(a["questionId"], run_id=run_id)
        self.assertTrue(scheme["lines"][0]["points"])

        lines = {sl["label"]: {"marks": [p["marks"] for p in sl["points"]],
                               "total": sum(p["marks"] for p in sl["points"])}
                 for sl in scheme["lines"]}
        out = self.lab.submit_results(run_id, [{
            "answerId": a["id"], "datasetVersion": version, "repeat": 1,
            "lines": lines, "reason": "test", "prompt": "p", "rawOutput": "r",
            "parseFailed": False,
        }])
        self.assertEqual(out["stored"], 1)

        self.lab.close_run(run_id)
        score = self.lab.score(run_id)
        self.assertTrue(score["closed"])
        self.assertIn("overall", score)

    def test_auth_error(self):
        bad = LabClient(base_url=self.base, key="msk_wrong")
        with self.assertRaises(LabError) as ctx:
            bad.dataset_version()
        self.assertEqual(ctx.exception.status, 401)

    def test_connection_error(self):
        dead = LabClient(base_url="http://127.0.0.1:1", key="k")
        with self.assertRaises(LabError) as ctx:
            dead.dataset_version()
        self.assertEqual(ctx.exception.status, 0)

    def test_run_split_validation(self):
        with self.assertRaises(LabError) as ctx:
            self.lab.create_run(harness_name="t", model="m", used_scheme=True,
                                git_commit="x", split="dev")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("split", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
