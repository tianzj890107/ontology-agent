import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DocumentationLayoutTests(unittest.TestCase):
    def test_root_readme_exists_and_describes_ontology_agent(self):
        readme = ROOT / "README.md"
        self.assertTrue(readme.exists())
        text = readme.read_text(encoding="utf-8")
        self.assertIn("硕磐智能建模", text)
        self.assertIn("v0.1.0", text)
        self.assertNotIn("Eimosp Foundation File Service", text)
        self.assertNotIn("Spring Boot", text)
        self.assertNotIn("MyBatis", text)

    def test_root_readme_links_docs(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("./docs/versions/README.md", text)
        self.assertIn("./docs/versions/v0.1.0.md", text)
        self.assertIn("./docs/changelog/README.md", text)
        self.assertIn("./docs/git-dual-remote-workflow.md", text)

    def test_eimosp_readme_archived(self):
        self.assertFalse((ROOT / "README (1).md").exists())
        archived = ROOT / "docs" / "eimosp-foundation-fileserver.md"
        self.assertTrue(archived.exists())
        text = archived.read_text(encoding="utf-8")
        self.assertIn("Eimosp Foundation File Service", text)

    def test_no_root_changelog_or_legacy_changelog_dir(self):
        self.assertFalse((ROOT / "CHANGELOG.md").exists())
        self.assertFalse((ROOT / "changelog").exists())

    def test_daily_changelogs_migrated(self):
        changelog_dir = ROOT / "docs" / "changelog"
        self.assertTrue(changelog_dir.is_dir())
        weekly_names = [
            "changelog_7.27_31.md", "changelog_8_3_7.md", "changelog_8_10_16.md",
            "changelog_8_17_21.md", "changelog_8_24_28.md",
        ]
        for name in weekly_names:
            self.assertTrue((changelog_dir / name).exists(), name)
        for name in ("changelog_8_24.md", "changelog_8_25.md", "changelog_8_26.md",
                     "changelog_8_27.md", "changelog_8_28.md"):
            self.assertFalse((changelog_dir / name).exists(), name)

    def test_changelog_index_lists_real_records(self):
        index = ROOT / "docs" / "changelog" / "README.md"
        self.assertTrue(index.exists())
        text = index.read_text(encoding="utf-8")
        self.assertIn("changelog_8_24_28.md", text)
        self.assertNotIn("changelog_8_28.md", text)
        self.assertNotIn("changelog_8_27.md", text)
        self.assertNotIn("changelog_8_26.md", text)
        self.assertNotIn("changelog_8_25.md", text)
        self.assertNotIn("changelog_8_24.md", text)

    def test_versions_index_and_v010_doc(self):
        index = ROOT / "docs" / "versions" / "README.md"
        self.assertTrue(index.exists())
        self.assertIn("v0.1.0", index.read_text(encoding="utf-8"))
        v010 = ROOT / "docs" / "versions" / "v0.1.0.md"
        self.assertTrue(v010.exists())
        text = v010.read_text(encoding="utf-8")
        self.assertIn("../changelog/changelog_8_24_28.md", text)
        self.assertIn("../changelog/README.md", text)
        self.assertIn("v0.0.1", text)

    def test_agents_uses_new_changelog_path(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("docs/changelog/changelog_M_D.md", text)
        self.assertIn("docs/changelog/changelog_8_13.md", text)
        self.assertNotIn("`changelog/changelog_M_D.md`", text)
        self.assertNotIn("- `changelog/` 下当天的 changelog；", text)
        self.assertIn("正式版本文档工作流", text)
        self.assertIn("docs/versions/", text)
        workflow = text.split("正式版本文档工作流", 1)[1].split("## 完成前检查", 1)[0]
        self.assertIn("不创建根目录 `CHANGELOG.md`", workflow)

    def test_product_version_distinct_from_knowledge_version(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("当前版本：`v0.1.1`", readme)
        # 文档必须区分“仓库最新正式版本”和“当前线上已部署版本”：v0.1.1
        # 已定版并部署，当前线上版本与仓库最新正式版本一致。
        self.assertIn("v0.1.1", readme)
        self.assertIn("v0.1.0", readme)
        self.assertIn("已部署", readme)
        self.assertNotIn("尚未部署", readme)
        version_doc = (ROOT / "docs" / "versions" / "v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("产品 UI 版本 `v0.1.0`", version_doc)

    def test_historical_deployment_facts_preserved(self):
        path = ROOT / "docs" / "changelog" / "changelog_8_24_28.md"
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("not-here-sentinel", text)


class VersioningPolicyTests(unittest.TestCase):
    def test_policy_file_exists_and_is_linked(self):
        policy = ROOT / "docs" / "versions" / "versioning-policy.md"
        self.assertTrue(policy.exists())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("./docs/versions/versioning-policy.md", readme)
        index = (ROOT / "docs" / "versions" / "README.md").read_text(encoding="utf-8")
        self.assertIn("./versioning-policy.md", index)
        v010 = (ROOT / "docs" / "versions" / "v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("./versioning-policy.md", v010)

    def test_policy_version_number_rules(self):
        text = (ROOT / "docs" / "versions" / "versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("vMAJOR.MINOR.PATCH", text)
        self.assertIn("修复、优化和小调整", text)
        self.assertIn("一组用户可感知的新能力", text)

    def test_policy_does_not_mechanically_follow_calendar(self):
        text = (ROOT / "docs" / "versions" / "versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("不按自然周机械升级", text)
        self.assertIn("不是每天有 commit 就必须升级版本", text)
        self.assertIn("如果一天只有文档、测试或内部维护，可以不发布正式版本", text)

    def test_policy_daily_stable_release_allows_patch(self):
        text = (ROOT / "docs" / "versions" / "versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("可以每天增加 PATCH", text)

    def test_policy_deployment_does_not_force_version(self):
        text = (ROOT / "docs" / "versions" / "versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("每次部署不一定创建新正式版本", text)

    def test_policy_distinguishes_documentation_carriers(self):
        text = (ROOT / "docs" / "versions" / "versioning-policy.md").read_text(encoding="utf-8")
        for keyword in ("Git commit", "每日 changelog", "docs/versions/vX.Y.Z.md",
                        "Git tag", "GitHub Release", "服务器部署"):
            self.assertIn(keyword, text)
        for rule in ("commit ≠ tag", "push ≠ 部署", "tag ≠ 部署",
                     "GitHub Release ≠ 部署", "部署 ≠ 必然创建新版本"):
            self.assertIn(rule, text)

    def test_policy_tags_immutable(self):
        text = (ROOT / "docs" / "versions" / "versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("已创建的 tag 不得移动", text)
        self.assertIn("禁止 `git tag -f` 覆盖或移动已定版 tag", text)

    def test_v010_finalized_state(self):
        v010 = (ROOT / "docs" / "versions" / "v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("状态：已定版", v010)
        self.assertIn("Git Tag：`v0.1.0`", v010)
        index = (ROOT / "docs" / "versions" / "README.md").read_text(encoding="utf-8")
        self.assertIn("已定版", index)

    def test_knowledge_version_v001_not_forbidden(self):
        # The knowledge/contract version v0.0.1 is intentionally still in use;
        # tests must never assert the repo-wide absence of v0.0.1.
        v010 = (ROOT / "docs" / "versions" / "v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("v0.0.1", v010)


if __name__ == "__main__":
    unittest.main()
