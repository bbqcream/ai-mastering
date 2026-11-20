import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.report import save_report


class ReportTests(unittest.TestCase):
    def test_failed_replace_keeps_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            save_report(path, {"status": "running"})
            with patch("core.report.os.replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    save_report(path, {"status": "complete"})
            self.assertEqual(json.loads(path.read_text()), {"status": "running"})
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_invalid_json_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            save_report(path, {"value": 1})
            with self.assertRaises(ValueError):
                save_report(path, {"value": float("nan")})
            self.assertEqual(json.loads(path.read_text()), {"value": 1})
