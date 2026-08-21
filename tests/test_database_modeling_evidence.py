import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

import oc_codex_server as server  # noqa: E402
from open_claude.modeling_reliability import (  # noqa: E402
    _template_sample_copy_issues,
    is_structural_blocker,
    validate_database_modeling_evidence,
)

BO_HEADER = "业务对象编码,业务对象名称,业务对象英文名,业务对象定义,数据类别"


def _bo_csv(objects):
    rows = [BO_HEADER]
    for index, name in enumerate(objects, 1):
        rows.append(f"BO{index:04d},{name},{name},定义,主数据")
    return ("\n".join(rows) + "\n").encode("utf-8")


class DatabaseModelingEvidenceTests(unittest.TestCase):
    def _make_run(self, with_db=True, with_schema=False,
                  template_objects=None, output_objects=None):
        root = Path(tempfile.mkdtemp())
        work = root / "work"
        output = root / "output"
        input_dir = root / "mission-input"
        work.mkdir()
        output.mkdir()
        input_dir.mkdir()
        if with_db:
            (input_dir / ".db_connection.json").write_text(
                json.dumps({"dbType": "POSTGRESQL", "sourceSchema": "public"}),
                encoding="utf-8")
        if with_schema:
            (work / "schema_extract.json").write_text(
                json.dumps({"tables": []}), encoding="utf-8")
        if template_objects is not None:
            sample_dir = input_dir / "本体元模型模板v0.0.1（含样例数据）-sheets"
            sample_dir.mkdir()
            (sample_dir / "02-业务对象.csv").write_text(
                _bo_csv(template_objects).decode("utf-8"), encoding="utf-8")
        blob = _bo_csv(output_objects) if output_objects is not None else b""
        return root, work, output, blob

    def test_database_mode_requires_schema_evidence(self):
        root, work, output, _ = self._make_run(with_db=True, with_schema=False)
        issues = validate_database_modeling_evidence(work, output)
        self.assertEqual([issue.code for issue in issues],
                         ["DATABASE_SCHEMA_EVIDENCE_MISSING"])
        self.assertTrue(is_structural_blocker(issues[0]))

    def test_database_mode_with_schema_passes(self):
        root, work, output, _ = self._make_run(with_db=True, with_schema=True)
        self.assertEqual(validate_database_modeling_evidence(work, output), [])

    def test_upload_mode_skips_schema_evidence(self):
        root, work, output, _ = self._make_run(with_db=False, with_schema=False)
        self.assertEqual(validate_database_modeling_evidence(work, output), [])

    def test_template_sample_copy_is_blocked(self):
        objects = ["供应商", "物料", "采购订单", "合同"]
        root, work, output, blob = self._make_run(
            template_objects=objects, output_objects=objects)
        issues = _template_sample_copy_issues(work, blob)
        self.assertEqual([issue.code for issue in issues],
                         ["FORMAL_OUTPUT_COPIED_TEMPLATE_SAMPLE"])
        self.assertTrue(is_structural_blocker(issues[0]))

    def test_different_objects_not_blocked(self):
        root, work, output, blob = self._make_run(
            template_objects=["供应商", "物料", "采购订单"],
            output_objects=["客户", "合同", "库存"])
        self.assertEqual(_template_sample_copy_issues(work, blob), [])

    def test_no_template_sample_not_blocked(self):
        root, work, output, blob = self._make_run(output_objects=["客户", "合同"])
        self.assertEqual(_template_sample_copy_issues(work, blob), [])

    def test_ensure_database_helpers_generates_extract_schema(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "mission-input").mkdir(parents=True)
            server.ensure_database_helpers(str(root), "db_config_path")
            extract = root / "mission-input" / "extract_schema.py"
            self.assertTrue(extract.is_file())
            content = extract.read_text(encoding="utf-8")
            self.assertIn("create_db_engine", content)
            self.assertIn("schema_extract.json", content)


if __name__ == "__main__":
    unittest.main()
