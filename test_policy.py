"""风险输出与CI策略契约，无真实模型或机器人调用。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run


class PolicyTests(unittest.TestCase):
    def test_report_exposes_risk_but_never_exits_before_notification(self):
        for risk in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                with patch.dict(os.environ, {
                    "AI_REVIEW_OPENAI_API_KEY": "test-key", "GITHUB_OUTPUT": str(output),
                    "RUNNER_TEMP": directory,
                }), patch.object(run, "collect", return_value=("diff", [])), \
                        patch.object(run, "review_with_fallback", return_value=("报告", [], risk)), \
                        patch.object(run, "notify_risk", return_value="通知状态") as notify:
                    self.assertEqual(run.main(), 0)
                    notify.assert_called_once()
                    self.assertEqual(notify.call_args.args[1], risk)
                    self.assertEqual(output.read_text().strip(), f"has_risk={str(risk).lower()}")

    def test_workflow_applies_policy_after_report(self):
        workflow = (Path(__file__).parent / "examples/ai-code-review.yml").read_text(encoding="utf-8")
        self.assertIn("AI_REVIEW_BLOCK_ON_RISK: 'false'", workflow)
        self.assertIn('"$AI_REVIEW_BLOCK_ON_RISK" == \'true\' && "$HAS_RISK" == \'true\'', workflow)
        self.assertIn("steps.review.outputs.has_risk", workflow)
        self.assertNotIn("    continue-on-error: true\n    permissions:", workflow)
        self.assertLess(workflow.index("生成中文风险报告"), workflow.index("应用风险阻断策略"))


if __name__ == "__main__":
    unittest.main()
