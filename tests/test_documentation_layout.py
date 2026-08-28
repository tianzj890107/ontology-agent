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
        legacy_names = [
            "changelog_7.27_31.md", "changelog_8_3_7.md", "changelog_8_10_16.md",
            "changelog_8_17_21.md", "changelog_8_24.md", "changelog_8_25.md",
            "changelog_8_26.md", "changelog_8_27.md", "changelog_8_28.md",
        ]
        for name in legacy_names:
            self.assertTrue((changelog_dir / name).exists(), name)

    def test_changelog_index_lists_real_records(self):
        index = ROOT / "docs" / "changelog" / "README.md"
        self.assertTrue(index.exists())
        text = index.read_text(encoding="utf-8")
        for name in ("changelog_8_28.md", "changelog_8_27.md", "changelog_8_24.md"):
            self.assertIn(name, text)

    def test_versions_index_and_v010_doc(self):
        index = ROOT / "docs" / "versions" / "README.md"
        self.assertTrue(index.exists())
        self.assertIn("v0.1.0", index.read_text(encoding="utf-8"))
        v010 = ROOT / "docs" / "versions" / "v0.1.0.md"
        self.assertTrue(v010.exists())
        text = v010.read_text(encoding="utf-8")
        self.assertIn("../changelog/changelog_8_28.md", text)
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
        # The workflow explicitly forbids a root CHANGELOG.md instead of
        # treating it as an active documentation path.
        self.assertIn("不创建根目录 `CHANGELOG.md`", workflow)

    def test_product_version_distinct_from_knowledge_version(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("当前版本：`v0.1.0`", readme)
        version_doc = (ROOT / "docs" / "versions" / "v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("产品 UI 版本 `v0.1.0`", version_doc)

    def test_historical_deployment_facts_preserved(self):
        # Historical changelogs keep their recorded deployment facts; the test
        # must not forbid "已部署" in archived records.
        for name in ("changelog_8_27.md", "changelog_8_28.md"):
            path = ROOT / "docs" / "changelog" / name
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("not-here-sentinel", text)


if __name__ == "__main__":
    unittest.main()
