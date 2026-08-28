import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "push_dual_remotes.py"


def run(cmd, cwd=None, check=True):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(
            "command failed: %s\nstdout:\n%s\nstderr:\n%s"
            % (" ".join(cmd), proc.stdout, proc.stderr)
        )
    return proc


def git(cwd, *args):
    return run(["git"] + list(args), cwd=cwd)


def init_local_repo(path, branch="20260727"):
    git(path, "init", "-b", branch)
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("test repo\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "initial")
    return git(path, "rev-parse", "HEAD").stdout.strip()


def init_bare(path):
    run(["git", "init", "--bare", str(path)])


def run_script(repo, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--allow-local-remotes"] + list(args),
        cwd=repo,
        capture_output=True,
        text=True,
    )


def bare_sha(bare, ref):
    proc = git(bare, "rev-parse", "--verify", ref)
    return proc.stdout.strip()


def bare_commit(bare, ref, message):
    """Append a commit on top of a bare repo ref using plumbing only."""
    parent = bare_sha(bare, ref)
    tree = git(bare, "rev-parse", parent + "^{tree}").stdout.strip()
    commit = git(bare, "commit-tree", tree, "-p", parent, "-m", message).stdout.strip()
    git(bare, "update-ref", ref, commit)
    return commit


class DualRemotePushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        self.origin = pathlib.Path(self.tmp.name) / "origin.git"
        self.personal = pathlib.Path(self.tmp.name) / "personal.git"
        self.repo.mkdir()
        init_bare(self.origin)
        init_bare(self.personal)

    def tearDown(self):
        self.tmp.cleanup()

    def _connect(self):
        git(self.repo, "remote", "add", "origin", str(self.origin))
        git(self.repo, "remote", "add", "personal", str(self.personal))

    def test_normal_push_mirrors_head_to_both_remotes(self):
        head = init_local_repo(self.repo)
        self._connect()
        proc = run_script(self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(bare_sha(self.origin, "refs/heads/20260727"), head)
        self.assertEqual(bare_sha(self.personal, "refs/heads/main"), head)
        self.assertIn("双远端推送成功", proc.stdout)

    def test_first_push_when_personal_main_missing(self):
        head = init_local_repo(self.repo)
        self._connect()
        proc = run_script(self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(bare_sha(self.personal, "refs/heads/main"), head)

    def test_repeat_run_is_idempotent(self):
        head = init_local_repo(self.repo)
        self._connect()
        self.assertEqual(run_script(self.repo).returncode, 0)
        self.assertEqual(run_script(self.repo).returncode, 0)
        self.assertEqual(bare_sha(self.personal, "refs/heads/main"), head)

    def test_dirty_worktree_rejected(self):
        init_local_repo(self.repo)
        self._connect()
        (self.repo / "dirty.txt").write_text("x", encoding="utf-8")
        proc = run_script(self.repo)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("未提交修改", proc.stderr)

    def test_detached_head_rejected(self):
        init_local_repo(self.repo)
        self._connect()
        git(self.repo, "checkout", "--detach", "HEAD")
        proc = run_script(self.repo)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("detached HEAD", proc.stderr)

    def test_missing_personal_remote_rejected(self):
        init_local_repo(self.repo)
        git(self.repo, "remote", "add", "origin", str(self.origin))
        proc = run_script(self.repo)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("缺少 remote personal", proc.stderr)

    def test_wrong_remote_url_rejected_without_local_override(self):
        init_local_repo(self.repo)
        git(self.repo, "remote", "add", "origin", "git@github.com:other/not-ontology.git")
        git(self.repo, "remote", "add", "personal", "git@github.com:wrong/repo.git")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("预期", proc.stderr)

    def test_personal_unique_commit_rejected(self):
        head = init_local_repo(self.repo)
        self._connect()
        self.assertEqual(run_script(self.repo).returncode, 0)
        # Append a personal-only commit on top of personal/main.
        bare_commit(self.personal, "refs/heads/main", "personal-only")
        proc = run_script(self.repo)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("存在本地没有的提交", proc.stderr)
        # personal/main must not have been overwritten.
        self.assertNotEqual(bare_sha(self.personal, "refs/heads/main"), head)

    def test_origin_unique_commit_rejected(self):
        head = init_local_repo(self.repo)
        self._connect()
        self.assertEqual(run_script(self.repo).returncode, 0)
        bare_commit(self.origin, "refs/heads/20260727", "origin-only")
        proc = run_script(self.repo)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("存在本地没有的提交", proc.stderr)

    def test_check_mode_does_not_change_remotes(self):
        head = init_local_repo(self.repo)
        self._connect()
        proc = run_script(self.repo, "--check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--check", proc.stdout)
        # Nothing was pushed.
        self.assertEqual(
            subprocess.run(
                ["git", "ls-remote", str(self.personal), "refs/heads/main"],
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "",
        )

    def test_mismatched_hashes_reported_as_failure(self):
        # After a successful push, force a divergence and verify the script
        # refuses to accept a mismatch as success.
        init_local_repo(self.repo)
        self._connect()
        self.assertEqual(run_script(self.repo).returncode, 0)
        bare_commit(self.personal, "refs/heads/main", "drift")
        proc = run_script(self.repo)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("存在本地没有的提交", proc.stderr)

    def test_no_force_push_flag(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("--force", source)


if __name__ == "__main__":
    unittest.main()
