import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RepositoryWorkflowContractTests(unittest.TestCase):
    def test_agents_requires_commit_and_push(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("必须将本次变更 `git commit` 并 `git push` 到当前 Git 分支", text)
        self.assertIn("`push` 仅指推送到 Git 远程仓库", text)

    def test_agents_forbids_deployment(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Agent 永远不得部署", text)
        self.assertIn("不得 SSH/SCP/rsync 到服务器", text)
        self.assertIn("不得重启", text)
        self.assertIn("不得在服务器执行 `git pull`", text)

    def test_agents_distinguishes_push_from_deploy(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("不代表发布或部署", text)
        self.assertIn("本地测试、本地构建和生成需要纳入 Git 的本地构建产物允许执行", text)
        self.assertIn("禁止 `git push --force`", text)

    def test_debug_md_no_legacy_deploy_instruction(self):
        text = (ROOT / "debug.md").read_text(encoding="utf-8")
        self.assertNotIn("优化做完之后完成部署", text)
        self.assertIn("优化完成并通过验证后，提交本次修改并 push 到当前 Git 分支", text)
        self.assertIn("禁止部署、禁止连接服务器、禁止重启服务", text)

    def test_debug_md_allows_push_but_not_deploy(self):
        text = (ROOT / "debug.md").read_text(encoding="utf-8")
        self.assertIn("允许并要求将本任务修改 commit 后 push 到当前 Git 分支", text)
        self.assertIn("禁止 `git push --force`", text)
        self.assertIn("不部署生产环境", text)

    def test_agent_knowledge_requires_push_without_deploy(self):
        text = (ROOT / "agent_knowledge" / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("再提交并部署", text)
        self.assertIn("提交并 push 到当前分支", text)
        self.assertIn("禁止部署或同步到服务器", text)

    def test_business_deployment_words_still_allowed(self):
        # The contract forbids deployment actions, not business words such as
        # "发布状态" or "发布事件"; historical facts remain untouched.
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("不代表发布或部署", agents)
        self.assertIn("不得发布到服务器", agents)
        deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
        self.assertIn("Agent 安全声明", deployment)
        self.assertIn("ssh company-server", deployment)


if __name__ == "__main__":
    unittest.main()
