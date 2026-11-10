"""报告产物与上传后通知契约，不访问真实机器人。"""

import tempfile
import unittest
from pathlib import Path

from report_artifact import write_report


class ArtifactTests(unittest.TestCase):
    def test_readable_report_escapes_model_html_and_separates_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = write_report(Path(directory), "## 明确问题\n<script>alert(1)</script>", ["覆盖不完整"])
            html = (target / "report.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)
            self.assertLess(html.index("明确问题"), html.index("<details>"))
            self.assertIn("覆盖不完整", (target / "report.md").read_text(encoding="utf-8"))

    def test_runtime_response_resolves_html_preview_not_download(self):
        import io
        import json
        import os
        from unittest.mock import patch
        from artifact_link import preview_url
        response = io.BytesIO(json.dumps({"value": [{"path": "ai-code-review-report-1/report.html",
            "contentLocation": "https://git.example/api/actions_pipeline/_apis/pipelines/workflows/10/artifacts/126/download"}]}).encode())
        with patch.dict(os.environ, {"GITHUB_SERVER_URL": "https://git.example", "GITHUB_REPOSITORY": "owner/repo",
                                    "GITHUB_RUN_ID": "10", "GITHUB_RUN_ATTEMPT": "1", "ACTIONS_RUNTIME_TOKEN": "fake"}), \
                patch("urllib.request.OpenerDirector.open", return_value=response):
            self.assertEqual(preview_url(), "https://git.example/owner/repo/actions/artifacts/126/preview/report.html")

    def test_notification_waits_for_uploaded_artifact(self):
        workflow = (Path(__file__).parent / "examples/ai-code-review.yml").read_text(encoding="utf-8")
        self.assertIn("AI_REVIEW_DEFER_NOTIFY: 'true'", workflow)
        self.assertIn("steps.artifact.outcome == 'success'", workflow)
        self.assertIn("/artifacts/ai-code-review-report-${{ gitea.run_attempt }}", workflow)
        self.assertLess(workflow.index("上传审查报告产物"), workflow.index("发送审查摘要与产物链接"))
