import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from grading.collect import grade, render


class GradingTests(unittest.TestCase):
    def test_invalid_archive_never_executes(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr("../../escape", "bad")
        with patch("grading.collect.subprocess.run") as run:
            result = grade("p01", "run1", "blob", raw.getvalue())
        self.assertEqual(result["grade"]["status"], "error")
        run.assert_not_called()

    def test_source_mismatch_never_executes(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr(
                "summary.json",
                json.dumps(
                    {"id": "run1", "participant": "p01", "source_sha256": "wrong"}
                ),
            )
            archive.writestr("workspace/src/main.py", "print('hello')")
        with patch("grading.collect.subprocess.run") as run:
            result = grade("p01", "run1", "blob", raw.getvalue())
        self.assertEqual(result["grade"]["status"], "error")
        run.assert_not_called()

    def test_comparison_requires_passing_same_conditions_and_escapes_notes(self):
        base = {
            "id": "run1",
            "participant": "p01",
            "variant": "baseline",
            "label": "기본",
            "condition_id": "same",
            "execution_status": "completed",
            "comparison_valid": True,
            "usage": {"input_tokens": 1000, "cached_input_tokens": 800},
            "grade": {"status": "passed"},
            "note": "<script>alert(1)</script>",
        }
        better = copy.deepcopy(base)
        better.update(id="run2", variant="custom", usage={"input_tokens": 500})
        failed = copy.deepcopy(better)
        failed.update(id="run3", grade={"status": "failed"})
        different = copy.deepcopy(better)
        different.update(id="run4", condition_id="different")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            render([base, better, failed, different], root)
            page = (root / "index.html").read_text()
            self.assertIn("50.0%", page)
            self.assertEqual(page.count("50.0%"), 1)
            self.assertNotIn("<script>", page)
            self.assertIn("&lt;script&gt;", page)
            self.assertIn('content="30"', page)
            self.assertEqual(len(json.loads((root / "data.json").read_text())), 4)

    def test_empty_board(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            render([], root)
            self.assertIn(
                "아직 제출된 실행이 없습니다", (root / "index.html").read_text()
            )
