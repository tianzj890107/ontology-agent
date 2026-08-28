import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RepositoryWorkflowContractTests(unittest.TestCase):
    def test_agents_requires_dual_remote_push(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("origin/20260727", text)
        self.assertIn("personal/main", text)
        self.assertIn("HEAD == origin/20260727 == personal/main", text)
        self.assertIn("python scripts/push_dual_remotes.py", text)

    def test_agents_forbids_personal_independent_commits(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("不允许产生个人仓库独有的代码提交", text)
        self.assertIn("不允许将 `personal/main` 的独有修改自动合回 `origin`", text)

    def test_agents_forbids_force_push(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("禁止 `git push --force` 和 `--force-with-lease`", text)

    def test_agents_distinguishes_push_from_deploy(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("不代表发布或部署", text)
        self.assertIn("双 push 后任务结束", text)
        self.assertIn("只有用户在未来新的明确指令中逐次单独授权具体部署目标和范围", text)

    def test_agents_partial_failure_must_not_be_reported_as_complete(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("任一远端失败时不得谎报任务全部完成", text)
        self.assertIn("报告部分成功", text)

    def test_agents_does_not_auto_push_tags(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("普通功能修改不自动 push tag", text)
        self.assertIn("只有用户明确创建正式版本时才创建并双推 tag", text)

    def test_agents_forbids_deployment(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Agent 永远不得部署", text)
        self.assertIn("不得 SSH/SCP/rsync 到服务器", text)
        self.assertIn("不得重启", text)
        self.assertIn("不得在服务器执行 `git pull`", text)

    def test_debug_md_uses_dual_remote_completion_criteria(self):
        text = (ROOT / "debug.md").read_text(encoding="utf-8")
        self.assertNotIn("优化做完之后完成部署", text)
        self.assertIn("origin 当前开发分支和 personal/main", text)
        self.assertIn("python scripts/push_dual_remotes.py", text)
        self.assertIn("禁止部署、禁止连接服务器、禁止重启服务", text)
        self.assertIn("禁止 `git push --force`", text)
        self.assertIn("不部署生产环境", text)

    def test_dual_remote_documentation_exists_and_linked(self):
        doc = ROOT / "docs" / "git-dual-remote-workflow.md"
        self.assertTrue(doc.exists())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("tianzj890107/ontology-agent", text)
        self.assertIn("zhenzhang0408/ontology-agent", text)
        self.assertIn("20260727", text)
        self.assertIn("main", text)
        self.assertIn("HEAD == origin/20260727 == personal/main", text)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("./docs/git-dual-remote-workflow.md", readme)

    def test_agent_knowledge_requires_push_without_deploy(self):
        text = (ROOT / "agent_knowledge" / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("再提交并部署", text)
        self.assertIn("提交并 push 到当前分支", text)
        self.assertIn("禁止部署或同步到服务器", text)

    def test_business_deployment_words_still_allowed(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("不代表发布或部署", agents)
        self.assertIn("不得发布到服务器", agents)
        deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
        self.assertIn("Agent 安全声明", deployment)
        self.assertIn("ssh company-server", deployment)

    def test_agents_links_versioning_policy(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("docs/versions/versioning-policy.md", text)
        self.assertIn("vMAJOR.MINOR.PATCH", text)
        self.assertIn("不按自然周机械升级", text)
        self.assertIn("每个 commit 不自动升级版本", text)
        self.assertIn("每次部署不一定创建正式版本", text)
        self.assertIn("每日稳定业务发布可以升级 PATCH", text)
        self.assertIn("已定版 tag 不得移动、覆盖或 force push", text)
        self.assertIn("GitHub Release 只有用户明确要求时创建", text)



if __name__ == "__main__":
    unittest.main()
