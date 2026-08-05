import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))
from open_claude.document_parser import extract_document, prepare_mission_documents


class DocumentParserTests(unittest.TestCase):
    @staticmethod
    def _docx(path: Path) -> None:
        document = '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>采购订单章节</w:t></w:r></w:p>
    <w:p><w:r><w:t>订单用于记录采购申请和履约过程。</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>字段</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>说明</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>订单号</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>业务主键</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>'''
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("word/document.xml", document)

    @staticmethod
    def _pptx(path: Path) -> None:
        slide = '''<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>供应商章节</a:t></a:r></a:p></p:txBody></p:sp>
    <p:sp><p:txBody><a:p><a:r><a:t>供应商负责提供物料。</a:t></a:r></a:p></p:txBody></p:sp>
    <p:graphicFrame><a:graphic><a:graphicData>
      <a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>编码</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>名称</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
      <a:tr><a:tc><a:txBody><a:p><a:r><a:t>V1</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>供应商</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl>
    </a:graphicData></a:graphic></p:graphicFrame>
  </p:spTree></p:cSld>
</p:sld>'''
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("ppt/slides/slide1.xml", slide)

    @staticmethod
    def _pdf(path: Path) -> None:
        # Build a small text-bearing PDF with pypdf itself; this avoids a
        # heavyweight PDF fixture while exercising the real PdfReader path.
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 720 Td (1. Purchase order chapter) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        with path.open("wb") as fh:
            writer.write(fh)

    def test_docx_pptx_and_pdf_extract_text_sections_and_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures = (("source.docx", self._docx), ("source.pptx", self._pptx), ("source.pdf", self._pdf))
            for name, create in fixtures:
                source = root / name
                create(source)
                manifest, error = extract_document(source, root / f"{source.stem}-document")
                self.assertIsNone(error, name)
                self.assertIsNotNone(manifest, name)
                self.assertTrue((root / f"{source.stem}-document" / "content.md").is_file())
                self.assertTrue((root / f"{source.stem}-document" / "manifest.json").is_file())
                content = (root / f"{source.stem}-document" / "content.md").read_text(encoding="utf-8")
                if name.endswith("docx"):
                    self.assertIn("采购订单章节", content)
                elif name.endswith("pptx"):
                    self.assertIn("供应商章节", content)
                else:
                    self.assertIn("Purchase order chapter", content)
                self.assertTrue(manifest["sections"], name)
                if not name.endswith("pdf"):
                    self.assertEqual(len(manifest["tables"]), 1, name)
                    self.assertIn("订单号" if name.endswith("docx") else "供应商",
                                  (root / f"{source.stem}-document" / "tables/001-table.csv").read_text(encoding="utf-8"))

    def test_prepare_mission_documents_is_fingerprinted_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_input = root / "mission-input"
            mission_input.mkdir()
            source = mission_input / "requirements.docx"
            self._docx(source)
            manifests, errors = prepare_mission_documents(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(manifests), 1)
            self.assertEqual(manifests[0]["source"], "mission-input/requirements.docx")
            bundle = root / manifests[0]["bundle"]
            first_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            manifests_again, errors_again = prepare_mission_documents(root)
            self.assertEqual(errors_again, [])
            self.assertEqual(manifests_again[0]["sourceSha256"], first_manifest["sourceSha256"])
            self.assertTrue((bundle / "tables/001-table.csv").is_file())


if __name__ == "__main__":
    unittest.main()
