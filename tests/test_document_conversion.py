import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from brain.document_cache import MarkdownDocumentCache
from brain.tools import _extract_full_text, clear_document_cache


class DocumentConversionTests(unittest.TestCase):
    def setUp(self):
        self._cache_dir = TemporaryDirectory()
        self._cache = MarkdownDocumentCache(Path(self._cache_dir.name))
        self._cache_patch = patch(
            "brain.tools._get_document_markdown_cache", return_value=self._cache
        )
        self._cache_patch.start()

    def tearDown(self):
        self._cache_patch.stop()
        self._cache_dir.cleanup()

    def test_docx_prefers_markitdown_output(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.docx"
            path.write_bytes(b"placeholder")
            with patch(
                "brain.tools._convert_with_markitdown",
                return_value="# 标题\n\n正文\n\n| 姓名 | 分数 |",
            ) as converter:
                content, error = _extract_full_text(path)

        self.assertEqual("", error)
        self.assertIn("# 标题", content)
        self.assertIn("| 姓名 | 分数 |", content)
        converter.assert_called_once_with(path)

    def test_pdf_falls_back_when_markitdown_fails(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pdf"
            path.write_bytes(b"placeholder")
            with patch(
                "brain.tools._convert_with_markitdown",
                side_effect=RuntimeError("unsupported PDF"),
            ), patch(
                "brain.tools._extract_pdf",
                return_value="legacy extracted text",
            ) as legacy:
                content, error = _extract_full_text(path)

        self.assertEqual("", error)
        self.assertEqual("legacy extracted text", content)
        legacy.assert_called_once_with(path)

    def test_docx_reports_both_failures(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.docx"
            path.write_bytes(b"placeholder")
            with patch(
                "brain.tools._convert_with_markitdown",
                side_effect=RuntimeError("markitdown failed"),
            ), patch(
                "brain.tools._extract_docx",
                side_effect=RuntimeError("legacy failed"),
            ):
                content, error = _extract_full_text(path)

        self.assertEqual("", content)
        self.assertIn("MarkItDown", error)
        self.assertIn("旧转换器", error)

    def test_identical_documents_share_one_markdown_cache_entry(self):
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.docx"
            second = Path(directory) / "second.docx"
            first.write_bytes(b"same document content")
            second.write_bytes(first.read_bytes())
            converter = lambda _: "# Cached Markdown"

            first_result = self._cache.get_or_create(first, converter)
            second_result = self._cache.get_or_create(
                second,
                lambda _: self.fail("identical source should use the cache"),
            )
            self.assertEqual(b"same document content", first.read_bytes())

        self.assertFalse(first_result.cache_hit)
        self.assertTrue(second_result.cache_hit)
        self.assertEqual(first_result.cache_path, second_result.cache_path)

    def test_cleanup_removes_only_cache_entries(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(b"source document")
            result = self._cache.get_or_create(source, lambda _: "# Markdown")
            self.assertTrue(result.cache_path.exists())

            self._cache.clear()

            self.assertFalse(result.cache_path.exists())
            self.assertEqual(b"source document", source.read_bytes())

    def test_clear_document_cache_requires_confirmation(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.docx"
            source.write_bytes(b"source document")
            self._cache.get_or_create(source, lambda _: "# Markdown")

            self.assertIn("确认", clear_document_cache(False))
            self.assertEqual(1, self._cache.stats()[0])
            self.assertIn("原始文件未被修改", clear_document_cache(True))
            self.assertEqual(0, self._cache.stats()[0])
            self.assertEqual(b"source document", source.read_bytes())

    def test_cache_evicts_old_entries_over_size_limit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = MarkdownDocumentCache(root / "cache", max_bytes=20)
            first = root / "first.pdf"
            second = root / "second.pdf"
            first.write_bytes(b"first source")
            second.write_bytes(b"second source")

            first_result = cache.get_or_create(first, lambda _: "a" * 16)
            second_result = cache.get_or_create(second, lambda _: "b" * 16)

            self.assertFalse(first_result.cache_path.exists())
            self.assertTrue(second_result.cache_path.exists())
            self.assertEqual(b"first source", first.read_bytes())
            self.assertEqual(b"second source", second.read_bytes())


if __name__ == "__main__":
    unittest.main()
