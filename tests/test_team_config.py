import os
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TeamModelConfigTests(unittest.TestCase):
    def test_team_default_model_must_be_in_exposed_catalogue(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "open-claude"),
            "LLM_PROVIDER": "team",
            "TEAM_MODEL": "not-a-team-model",
            "TEAM_MODELS": "model-a,model-a,model-b",
        })
        script = (
            "from open_claude.config import DEFAULT_MODEL, get_model, TEAM_MODEL_IDS, configured_models; "
            "print(DEFAULT_MODEL); print(get_model()); print(TEAM_MODEL_IDS); "
            "print([m['id'] for m in configured_models()])"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "model-a")
        self.assertEqual(lines[1], "model-a")
        self.assertIn("model-a", lines[2])
        self.assertIn("model-b", lines[2])
        self.assertEqual(lines[3], "['model-a', 'model-b']")

    def test_shared_model_keeps_qwen_provider_when_team_catalogue_overlaps(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "open-claude"),
            "LLM_PROVIDER": "qwen",
            "QWEN_TEXT_MODELS": "shared-qwen,qwen-only",
            "QWEN_VISION_MODELS": "",
            "TEAM_MODELS": "shared-qwen,team-only",
        })
        script = (
            "from open_claude.config import configured_models, get_model_provider; "
            "print([m['id'] for m in configured_models() if m['id'] in {'shared-qwen', 'team-only'}]); "
            "print(get_model_provider('shared-qwen'))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "['shared-qwen']")
        self.assertEqual(lines[1], "qwen")

if __name__ == "__main__":
    unittest.main()
