import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import oc_codex_server as server  # noqa: E402


class TaskWorkspaceFileTreeTests(unittest.TestCase):
    def test_mission_work_is_listed_with_all_standard_task_directories(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for directory in ("mission-input", "mission-work", "mission-output", "project-shared"):
                (root / directory).mkdir()
            (root / "mission-input" / "input.csv").write_text("input", encoding="utf-8")
            (root / "mission-input" / "reference-v0.0.1-sheets").mkdir()
            (root / "mission-input" / "reference-v0.0.1-sheets" / "manifest.json").write_text("{}", encoding="utf-8")
            (root / "mission-work" / "modeling_state.json").write_text('{"version": 1}', encoding="utf-8")
            (root / "mission-work" / "business_object_decisions.csv").write_text("audit", encoding="utf-8")
            (root / "mission-work" / "nested").mkdir()
            (root / "mission-work" / "nested" / "audit.py").write_text("pass", encoding="utf-8")
            (root / "mission-output" / "result.csv").write_text("result", encoding="utf-8")
            (root / "project-shared" / "reference.md").write_text("ref", encoding="utf-8")

            files = server.list_project_files(str(root), "")
            paths = {item["path"] for item in files}
            self.assertEqual(paths, {
                "mission-input/input.csv",
                "mission-input/reference-v0.0.1-sheets/manifest.json",
                "mission-work/modeling_state.json",
                "mission-work/business_object_decisions.csv",
                "mission-work/nested/audit.py",
                "mission-output/result.csv",
                "project-shared/reference.md",
            })
            display_paths = {item["displayPath"] for item in files}
            self.assertEqual(display_paths, {
                "input/input.csv",
                "root/work/reference-v0.0.1-sheets/manifest.json",
                "root/work/modeling_state.json",
                "work/business_object_decisions.csv",
                "root/work/nested/audit.py",
                "output/result.csv",
                "root/reference.md",
            })

            state_path = server.resolve_file_in_base(str(root), "mission-work/modeling_state.json")
            self.assertEqual(Path(state_path).read_text(encoding="utf-8"), '{"version": 1}')

    def test_runtime_updates_are_visible_without_copying_to_output(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "mission-work").mkdir()
            (root / "mission-output").mkdir()
            state = root / "mission-work" / "modeling_state.json"
            state.write_text("version=1", encoding="utf-8")
            self.assertIn("mission-work/modeling_state.json",
                          {item["path"] for item in server.list_project_files(str(root))})
            state.write_text("version=2", encoding="utf-8")
            listed = {item["path"]: item for item in server.list_project_files(str(root))}
            self.assertIn("mission-work/modeling_state.json", listed)
            resolved = server.resolve_file_in_base(str(root), "mission-work/modeling_state.json")
            self.assertEqual(Path(resolved).read_text(encoding="utf-8"), "version=2")
            self.assertFalse((root / "mission-output" / "modeling_state.json").exists())

    def test_mission_work_isolated_by_task_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            task_a = root / "tasks" / "A"
            task_b = root / "tasks" / "B"
            (task_a / "mission-work").mkdir(parents=True)
            (task_b / "mission-work").mkdir(parents=True)
            (task_a / "mission-work" / "a.json").write_text("A", encoding="utf-8")
            (task_b / "mission-work" / "b.json").write_text("B", encoding="utf-8")
            files_a = {item["path"] for item in server.list_project_files(str(task_a))}
            files_b = {item["path"] for item in server.list_project_files(str(task_b))}
            self.assertEqual(files_a, {"mission-work/a.json"})
            self.assertEqual(files_b, {"mission-work/b.json"})

    def test_output_collector_does_not_move_work_files_into_formal_output(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "mission-work").mkdir()
            (root / "mission-work" / "business_objects.csv").write_text("audit", encoding="utf-8")
            moved = server.ensure_mission_output_files(
                str(root), {"taskType": "modeling", "expectedFiles": ["business_objects.csv"]})
            self.assertEqual(moved, [])
            self.assertFalse((root / "mission-output" / "business_objects.csv").exists())

    def test_api_files_route_returns_mission_work(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "mission-work").mkdir()
            (root / "mission-work" / "modeling_state.json").write_text("{}", encoding="utf-8")
            handler = object.__new__(server.Handler)
            handler.path = "/api/files?project=fixture"
            handler.headers = {}
            response = []
            handler._requires_auth = lambda path: False
            handler._current_user = lambda: "test-user"
            handler._send_json = lambda payload, status=200: response.append((status, payload))
            with patch.object(server, "bind_mission_project", return_value="fixture"), \
                    patch.object(server, "mission_task_cwd", return_value=str(root)), \
                    patch.object(server, "project_path", return_value=str(root)):
                handler.do_GET()
            self.assertEqual(response[0][0], 200)
            self.assertIn("mission-work/modeling_state.json",
                          {item["path"] for item in response[0][1]["files"]})

    def test_runtime_dependency_files_cannot_hide_public_workspace_files(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            runtime = root / "pylibs"
            runtime.mkdir()
            for index in range(2100):
                (runtime / f"dependency_{index:04d}.py").write_text("# runtime\n", encoding="utf-8")
            (root / "mission-output").mkdir()
            (root / "mission-output" / "business_objects.csv").write_text("code\nBO1\n", encoding="utf-8")
            (root / "mission-work").mkdir()
            (root / "mission-work" / "modeling_state.json").write_text("{}", encoding="utf-8")

            files = server.list_project_files(str(root))
            paths = {item["path"] for item in files}
            self.assertEqual(len(files), 2)
            self.assertEqual(paths, {
                "mission-output/business_objects.csv",
                "mission-work/modeling_state.json",
            })


if __name__ == "__main__":
    unittest.main()
