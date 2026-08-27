import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude import workspace_paths  # noqa: E402
from open_claude.workspace_paths import (  # noqa: E402
    WorkspacePathError,
    ensure_workspace_dirs,
    input_dir,
    normalize_relpath,
    output_dir,
    resolve_workspace_path,
    validate_task_workspace,
    work_dir,
)

import oc_codex_server as server  # noqa: E402


class WorkspacePathsContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo_root = ROOT
        self.source_root = ROOT / "open-claude"
        self.home = Path(os.path.expanduser("~"))

    def tearDown(self):
        self.tmp.cleanup()

    def _validate(self, cwd):
        return validate_task_workspace(
            cwd,
            allowed_root=self.base,
            repo_root=self.repo_root,
            source_root=self.source_root,
            home_dir=self.home,
        )

    def test_repo_root_rejected_as_workspace(self):
        with self.assertRaises(WorkspacePathError):
            self._validate(self.repo_root)

    def test_source_dir_rejected_as_workspace(self):
        with self.assertRaises(WorkspacePathError):
            self._validate(self.source_root)

    def test_home_dir_rejected_as_workspace(self):
        with self.assertRaises(WorkspacePathError):
            self._validate(self.home)

    def test_empty_path_rejected(self):
        for empty in ("", None, "   "):
            with self.subTest(empty=empty):
                with self.assertRaises(WorkspacePathError):
                    self._validate(empty)

    def test_allowed_root_itself_rejected_as_workspace(self):
        with self.assertRaises(WorkspacePathError):
            self._validate(self.base)

    def test_outside_allowed_root_rejected(self):
        outside = self.base.parent / "outside-workspace"
        outside.mkdir(exist_ok=True)
        with self.assertRaises(WorkspacePathError):
            self._validate(outside)

    def test_relative_escape_rejected(self):
        with self.assertRaises(WorkspacePathError):
            self._validate(os.path.join(self.base, "task", "..", "..", "escape"))

    def test_symlink_escape_rejected(self):
        real_outside = self.base.parent / "symlink-escape-target"
        real_outside.mkdir(exist_ok=True)
        task = self.base / "task-valid"
        task.mkdir(exist_ok=True)
        link = task / "escape"
        link.symlink_to(real_outside, target_is_directory=True)
        with self.assertRaises(WorkspacePathError):
            self._validate(link)

    def test_valid_task_dir_ok(self):
        task = self.base / "tasks" / "RM123456789"
        task.mkdir(parents=True)
        self.assertEqual(self._validate(task), str(task.resolve()))

    def test_ensure_workspace_dirs_creates_only_canonical(self):
        task = self.base / "tasks" / "RM123456789"
        task.mkdir(parents=True)
        created = ensure_workspace_dirs(task)
        self.assertEqual({Path(p).name for p in created}, {"input", "work", "output"})
        for name in ("input", "work", "output"):
            self.assertTrue((task / name).is_dir())
        for name in ("mission-input", "mission-work", "mission-output"):
            self.assertFalse((task / name).exists())

    def test_canonical_wins_and_legacy_read_fallback(self):
        task = self.base / "tasks" / "RM123456789"
        task.mkdir(parents=True)
        for name in ("input", "mission-input", "work", "mission-work", "output", "mission-output"):
            (task / name).mkdir()
        (task / "output" / "formal.csv").write_text("canonical", encoding="utf-8")
        (task / "mission-output" / "formal.csv").write_text("legacy", encoding="utf-8")
        self.assertEqual(
            Path(output_dir(task)).name, "output")
        self.assertEqual(
            Path(resolve_workspace_path(task, "output/formal.csv")).read_text(encoding="utf-8"),
            "canonical")
        # Legacy logical path resolves to the canonical physical file.
        self.assertEqual(
            Path(resolve_workspace_path(task, "mission-output/formal.csv")).read_text(encoding="utf-8"),
            "canonical")
        # Legacy-only files remain readable.
        (task / "mission-work" / "legacy_state.json").write_text("legacy", encoding="utf-8")
        self.assertEqual(
            Path(resolve_workspace_path(task, "mission-work/legacy_state.json")).read_text(encoding="utf-8"),
            "legacy")
        self.assertEqual(
            Path(resolve_workspace_path(task, "work/legacy_state.json")).read_text(encoding="utf-8"),
            "legacy")

    def test_writes_always_target_canonical(self):
        task = self.base / "tasks" / "RM123456789"
        task.mkdir(parents=True)
        (task / "mission-work").mkdir()
        # Legacy-only tasks keep reading from the legacy directory...
        self.assertEqual(Path(work_dir(task)).name, "mission-work")
        # ...but new writes always land in the canonical directory.
        target = resolve_workspace_path(task, "work/state.json", must_exist=False)
        self.assertEqual(Path(target).parent.name, "work")

    def test_normalize_relpath_maps_legacy_to_canonical(self):
        self.assertEqual(normalize_relpath("mission-output/business_objects.csv"),
                         "output/business_objects.csv")
        self.assertEqual(normalize_relpath("mission-work/modeling_state.json"),
                         "work/modeling_state.json")
        self.assertEqual(normalize_relpath("mission-input/data.csv"), "input/data.csv")
        self.assertEqual(normalize_relpath("output/business_objects.csv"),
                         "output/business_objects.csv")

    def test_47313_create_task_only_creates_canonical_dirs(self):
        with tempfile.TemporaryDirectory() as sandbox_tmp:
            sandbox = Path(sandbox_tmp)
            old_sandbox = server.SANDBOX_DIR
            old_tasks = server.TASKS
            old_tasks_lock = server.TASKS_LOCK
            server.SANDBOX_DIR = str(sandbox)
            server.TASKS = {}
            try:
                task = server.create_task("", repository_id="1", task_code="RM123456789",
                                          task_type="modeling", user_id="u")
                self.assertIsNotNone(task)
                cwd = Path(task.cwd)
                self.assertEqual({p.name for p in cwd.iterdir()},
                                 {"input", "work", "output", "project-shared"})
                self.assertFalse((cwd / "mission-input").exists())
                self.assertFalse((cwd / "mission-work").exists())
                self.assertFalse((cwd / "mission-output").exists())
                self.assertNotEqual(cwd.resolve(), ROOT.resolve())
                self.assertNotEqual(cwd.resolve(), (ROOT / "open-claude").resolve())
            finally:
                server.SANDBOX_DIR = old_sandbox
                server.TASKS = old_tasks
                server.TASKS_LOCK = old_tasks_lock

    def test_47314_run_create_only_creates_canonical_dirs(self):
        from standalone_modeling_server import RunStore
        with tempfile.TemporaryDirectory() as store_tmp:
            store = RunStore(store_tmp)
            run = store.create("NATURAL_LANGUAGE", "prompt")
            root = Path(run.root)
            self.assertEqual({p.name for p in root.iterdir()}, {"input", "work", "output"})
            for name in ("mission-input", "mission-work", "mission-output"):
                self.assertFalse((root / name).exists())
            store.close_managers()


if __name__ == "__main__":
    unittest.main()
