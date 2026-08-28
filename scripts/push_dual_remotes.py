#!/usr/bin/env python3
"""Push the same local HEAD to origin/<branch> and personal/main.

Safety-focused dual-remote mirror push:

- origin      -> tianzj890107/ontology-agent   (branch 20260727)
- personal    -> zhenzhang0408/ontology-agent   (branch main)

Usage:
    python scripts/push_dual_remotes.py [--check]
    python scripts/push_dual_remotes.py --source-branch 20260727 \
        --origin-branch 20260727 --personal-branch main

--check only inspects configuration and remote hashes without pushing.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ORIGIN_OWNER_REPO = "tianzj890107/ontology-agent"
PERSONAL_OWNER_REPO = "zhenzhang0408/ontology-agent"
DEFAULT_SOURCE_BRANCH = "20260727"
DEFAULT_ORIGIN_BRANCH = "20260727"
DEFAULT_PERSONAL_BRANCH = "main"


class PushError(RuntimeError):
    pass


def run_git(args, check=True, capture=True):
    cmd = ["git"] + args
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    if check and proc.returncode != 0:
        raise PushError(
            "git %s failed: %s" % (" ".join(args), (proc.stderr or proc.stdout or "").strip())
        )
    return proc


def git_root():
    proc = run_git(["rev-parse", "--show-toplevel"])
    return Path(proc.stdout.strip())


def current_branch():
    proc = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def remote_url(name):
    proc = run_git(["remote", "get-url", name])
    return proc.stdout.strip()


def parse_owner_repo(url):
    """Return (owner, repo) for GitHub SSH/HTTPS URLs, or None."""
    url = url.strip().rstrip("/")
    ssh = re.match(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url)
    if ssh:
        return ssh.group(1), ssh.group(2).removesuffix(".git")
    https = re.match(r"^https?://github\.com/([^/]+)/(.+?)(?:\.git)?$", url)
    if https:
        return https.group(1), https.group(2).removesuffix(".git")
    return None


def verify_remote(remote_name, expected_owner_repo, allow_local):
    url = remote_url(remote_name)
    if allow_local:
        return url
    parsed = parse_owner_repo(url)
    if parsed is None:
        raise PushError(
            "remote %s URL %r 无法识别为 GitHub 仓库；预期 %s"
            % (remote_name, url, expected_owner_repo)
        )
    actual = "%s/%s" % parsed
    if actual != expected_owner_repo:
        raise PushError(
            "remote %s 指向 %r，预期 %r；拒绝继续" % (remote_name, actual, expected_owner_repo)
        )
    return url


def worktree_clean():
    proc = run_git(["status", "--porcelain"])
    return not proc.stdout.strip()


def remote_sha(remote_name, ref):
    proc = run_git(["ls-remote", remote_name, ref], check=False)
    if proc.returncode != 0:
        raise PushError(
            "无法读取 remote %s：%s" % (remote_name, (proc.stderr or "").strip())
        )
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    return None


def is_ancestor(ancestor, descendant):
    proc = run_git(
        ["merge-base", "--is-ancestor", ancestor, descendant], check=False
    )
    return proc.returncode == 0


def verify_remote_state(remote_name, remote_sha_value, head_sha):
    if remote_sha_value is None:
        return "missing"
    if remote_sha_value == head_sha:
        return "equal"
    if is_ancestor(remote_sha_value, head_sha):
        return "ancestor"
    raise PushError(
        "remote %s 存在本地没有的提交 %s；禁止 force push 或自动合并，拒绝 push"
        % (remote_name, remote_sha_value[:12])
    )


def hashes_match(head, origin_sha, personal_sha):
    return head == origin_sha == personal_sha


def do_push(remote_name, head_sha, branch):
    proc = run_git(
        ["push", remote_name, "%s:refs/heads/%s" % (head_sha, branch)],
        check=False,
    )
    if proc.returncode != 0:
        raise PushError(
            "push 到 %s/%s 失败：%s"
            % (remote_name, branch, (proc.stderr or proc.stdout or "").strip())
        )
    return proc.stdout + proc.stderr


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dual-remote mirror push")
    parser.add_argument("--check", action="store_true", help="只检查，不推送")
    parser.add_argument("--source-branch", default=DEFAULT_SOURCE_BRANCH)
    parser.add_argument("--origin-branch", default=DEFAULT_ORIGIN_BRANCH)
    parser.add_argument("--personal-branch", default=DEFAULT_PERSONAL_BRANCH)
    parser.add_argument(
        "--allow-local-remotes",
        action="store_true",
        help="测试专用：跳过 GitHub 仓库 URL 校验（允许本地 bare remote）",
    )
    args = parser.parse_args(argv)

    # 1. Must be a git repository.
    try:
        root = git_root()
    except PushError as exc:
        print("错误：当前目录不是 Git 仓库。", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2

    # 2. Current branch; reject detached HEAD.
    branch = current_branch()
    if not branch:
        print("错误：当前处于 detached HEAD，拒绝 push。", file=sys.stderr)
        return 2
    # 3. Default requires the current development branch.
    if branch != args.source_branch:
        print(
            "错误：当前分支 %s 不是预期开发分支 %s；拒绝 push。"
            % (branch, args.source_branch),
            file=sys.stderr,
        )
        return 2

    # 4/5. Remotes exist.
    for name in ("origin", "personal"):
        try:
            remote_url(name)
        except PushError:
            print("错误：缺少 remote %s；无法执行双远端推送。" % name, file=sys.stderr)
            return 2

    # 6/7. URL mappings.
    try:
        origin_url = verify_remote("origin", ORIGIN_OWNER_REPO, args.allow_local_remotes)
        personal_url = verify_remote("personal", PERSONAL_OWNER_REPO, args.allow_local_remotes)
    except PushError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2

    # 8. Working tree must be clean (no uncommitted changes).
    if not worktree_clean():
        print("错误：工作区存在未提交修改，拒绝 push。", file=sys.stderr)
        return 2

    # 9. Local HEAD.
    head_sha = run_git(["rev-parse", "HEAD"]).stdout.strip()

    # 10/11. Read remote target refs and validate ancestry.
    origin_ref = "refs/heads/%s" % args.origin_branch
    personal_ref = "refs/heads/%s" % args.personal_branch
    origin_sha = None
    personal_sha = None
    origin_unreachable = None
    personal_unreachable = None
    try:
        origin_sha = remote_sha("origin", origin_ref)
    except PushError as exc:
        origin_unreachable = exc
    try:
        personal_sha = remote_sha("personal", personal_ref)
    except PushError as exc:
        personal_unreachable = exc

    if origin_unreachable:
        print("错误：无法读取 origin：%s" % origin_unreachable, file=sys.stderr)
        print("无法确认 origin 状态，双远端推送未执行。", file=sys.stderr)
        return 2

    try:
        origin_state = verify_remote_state("origin", origin_sha, head_sha)
    except PushError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2
    if personal_unreachable:
        personal_state = "unreachable"
    else:
        try:
            personal_state = verify_remote_state("personal", personal_sha, head_sha)
        except PushError as exc:
            print("错误：%s" % exc, file=sys.stderr)
            return 2

    print("本地 HEAD: %s" % head_sha)
    print("origin  (%s) %s: %s (%s)" % (origin_url, origin_ref, origin_sha or "(缺失)", origin_state))
    print("personal (%s) %s: %s (%s)" % (personal_url, personal_ref, personal_sha or "(缺失)", personal_state))

    if args.check:
        print("--check：未执行任何 push。")
        if personal_unreachable:
            print("注意：personal 远端当前不可达（%s）；首次推送前请先创建或确认个人私有仓库。"
                  % str(personal_unreachable).strip().splitlines()[0])
        return 0

    # 12/13. Push origin first, then personal.
    try:
        print("推送到 origin/%s ..." % args.origin_branch)
        do_push("origin", head_sha, args.origin_branch)
    except PushError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        print("双远端推送失败：origin 未成功，任务未完成。", file=sys.stderr)
        return 1

    try:
        print("推送到 personal/%s ..." % args.personal_branch)
        do_push("personal", head_sha, args.personal_branch)
    except PushError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        print(
            "部分成功：origin 已推送，personal 失败；两个远端暂时不一致。"
            "请修复 personal 的权限或网络（或先创建个人私有仓库）后，重新执行相同 HEAD 的 push；"
            "不回滚 origin、不 force push、不创建补偿 commit。",
            file=sys.stderr,
        )
        return 1

    # 16/17/18. Post-push verification via ls-remote.
    try:
        new_origin_sha = remote_sha("origin", origin_ref)
    except PushError as exc:
        print("错误：push 后读取 origin 失败：%s" % exc, file=sys.stderr)
        return 1
    try:
        new_personal_sha = remote_sha("personal", personal_ref)
    except PushError as exc:
        print("错误：push 后读取 personal 失败：%s" % exc, file=sys.stderr)
        print(
            "部分成功：origin 已推送，personal 校验失败；两个远端暂时不一致。"
            "请修复 personal 的权限或网络后重新执行相同 HEAD 的 push；不回滚 origin、不 force push。",
            file=sys.stderr,
        )
        return 1
    if not hashes_match(head_sha, new_origin_sha, new_personal_sha):
        print(
            "错误：push 后 hash 不一致：HEAD=%s origin=%s personal=%s"
            % (head_sha, new_origin_sha or "(缺失)", new_personal_sha or "(缺失)"),
            file=sys.stderr,
        )
        return 1

    print("双远端推送成功：HEAD == origin/%s == personal/%s == %s"
          % (args.origin_branch, args.personal_branch, head_sha))
    return 0


if __name__ == "__main__":
    sys.exit(main())
