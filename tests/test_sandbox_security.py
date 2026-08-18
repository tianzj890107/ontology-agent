import os
import platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude.sandbox import (  # noqa: E402
    PUBLIC_VIOLATION,
    SandboxViolation,
    TaskSandboxBoundary,
)
from open_claude.tools import execute_tool  # noqa: E402


class SandboxPathSecurityTests(unittest.TestCase):
    def setUp(self):
        self._old_root = os.environ.get("OC_SANDBOX_ROOT")
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.tasks = self.base / "tasks"
        self.task = self.tasks / "RM123"
        self.sibling = self.tasks / "RM1234"
        self.outside = self.base / "outside"
        self.task.mkdir(parents=True)
        self.sibling.mkdir()
        self.outside.mkdir()
        os.environ["OC_SANDBOX_ROOT"] = str(self.tasks)

    def tearDown(self):
        if self._old_root is None:
            os.environ.pop("OC_SANDBOX_ROOT", None)
        else:
            os.environ["OC_SANDBOX_ROOT"] = self._old_root
        self.tmp.cleanup()

    def boundary(self):
        return TaskSandboxBoundary(self.task, allowed_root=self.tasks)

    def test_relative_and_normalized_paths_stay_in_current_task(self):
        boundary = self.boundary()
        expected = os.path.realpath(self.task / "mission-output" / "test.csv")
        self.assertEqual(boundary.resolve("mission-output/test.csv"), expected)
        self.assertEqual(boundary.resolve("./mission-output/a/../test.csv"), expected)
        self.assertEqual(boundary.resolve("mission-output//test.csv"), expected)
        self.assertEqual(boundary.resolve(expected), expected)

    def test_relative_absolute_and_prefix_escape_are_rejected(self):
        boundary = self.boundary()
        attempts = (
            "../test",
            "../../test",
            "mission-output/../../test",
            str(self.outside / "test"),
            str(self.sibling / "test"),
            str(self.tasks / "mission-output" / "test"),
        )
        for path in attempts:
            with self.subTest(path=path), self.assertRaises(SandboxViolation):
                boundary.resolve(path)

    def test_symlink_outside_is_rejected_and_symlink_inside_is_allowed(self):
        outside_file = self.outside / "secret.txt"
        outside_file.write_text("secret", encoding="utf-8")
        outside_link = self.task / "outside-link"
        outside_link.symlink_to(self.outside)
        with self.assertRaises(SandboxViolation):
            self.boundary().resolve("outside-link/secret.txt")

        inside_dir = self.task / "mission-output"
        inside_dir.mkdir()
        inside_file = inside_dir / "safe.txt"
        inside_file.write_text("safe", encoding="utf-8")
        inside_link = self.task / "inside-link"
        inside_link.symlink_to(inside_dir, target_is_directory=True)
        self.assertEqual(
            self.boundary().resolve("inside-link/safe.txt"), os.path.realpath(inside_file)
        )

    def test_file_tools_use_the_same_boundary(self):
        self.assertIn("outside the current task workspace", execute_tool(
            "Read", {"file_path": str(self.outside / "secret.txt")}, str(self.task)
        ))
        self.assertIn("outside the current task workspace", execute_tool(
            "Write", {"file_path": "../escape.txt", "content": "bad"}, str(self.task)
        ))
        self.assertIn("outside the current task workspace", execute_tool(
            "Edit", {"file_path": str(self.sibling / "x.txt"),
                      "old_string": "x", "new_string": "y"}, str(self.task)
        ))
        safe = self.task / "mission-output" / "safe.txt"
        self.assertIn("Created file", execute_tool(
            "Write", {"file_path": "mission-output/safe.txt", "content": "before"}, str(self.task)
        ))
        self.assertIn("Edited", execute_tool(
            "Edit", {"file_path": str(safe), "old_string": "before", "new_string": "after"},
            str(self.task),
        ))
        self.assertIn("after", execute_tool(
            "Read", {"file_path": "./mission-output//safe.txt"}, str(self.task)
        ))

    @unittest.skipUnless(
        platform.system() == "Linux" and shutil.which("bwrap"),
        "Linux bubblewrap is required for shell isolation tests",
    )
    def test_shell_cannot_reach_sibling_or_parent_output(self):
        protected_dir = self.tasks / "mission-output"
        protected_dir.mkdir()
        protected = protected_dir / "protected.txt"
        protected.write_text("PROTECTED_CONTENT", encoding="utf-8")
        self.assertNotIn("PROTECTED_CONTENT", execute_tool(
            "Bash", {"command": f"cat {protected}"}, str(self.task)
        ))
        execute_tool("Bash", {"command": f"rm -rf \"{protected_dir}\""}, str(self.task))
        self.assertTrue(protected.exists(), "the real incident regression must preserve the sibling output")

    @unittest.skipUnless(
        platform.system() == "Linux" and shutil.which("bwrap"),
        "Linux bubblewrap is required for shell isolation tests",
    )
    def test_shell_allows_task_relative_and_absolute_paths(self):
        output = self.task / "mission-output"
        output.mkdir()
        absolute_file = output / "absolute.txt"
        result = execute_tool(
            "Bash",
            {"command": f"mkdir -p mission-output && echo ok > \"{absolute_file}\" && cat mission-output/absolute.txt"},
            str(self.task),
        )
        self.assertIn("ok", result)
        self.assertEqual(absolute_file.read_text(encoding="utf-8").strip(), "ok")

    @unittest.skipUnless(
        platform.system() == "Linux" and shutil.which("bwrap"),
        "Linux bubblewrap is required for shell isolation tests",
    )
    def test_shell_expansion_and_symlink_cannot_escape(self):
        outside_file = self.outside / "secret.txt"
        outside_file.write_text("SECRET_CONTENT", encoding="utf-8")
        link = self.task / "link"
        link.symlink_to(self.outside, target_is_directory=True)
        result = execute_tool(
            "Bash",
            {"command": f'p="{outside_file}"; cat "$p"; cat "{link}/secret.txt"'},
            str(self.task),
        )
        self.assertNotIn("SECRET_CONTENT", result)

    def test_boundary_error_is_not_an_internal_path_dump(self):
        result = execute_tool("Read", {"file_path": "/etc/passwd"}, str(self.task))
        self.assertEqual(result, f"Error: {PUBLIC_VIOLATION}")
        self.assertNotIn(str(self.tasks), result)


if __name__ == "__main__":
    unittest.main()
