"""危险度评分契约、真实分数通知排序和旧模型兼容。"""

import json
import unittest

from notification_summary import summarize
from report import parse_result
from risk_score import score_of
from test_notify import FINDING


class ScoreTests(unittest.TestCase):
    def test_invalid_scores_and_reasons_rejected(self):
        for score in (-1, 101, True, "90", None, 1.5):
            with self.subTest(score=score), self.assertRaises(ValueError):
                score_of({**FINDING, "score": score, "score_reason": "实际影响"})
        with self.assertRaises(ValueError):
            score_of({**FINDING, "score": 95})

    def test_display_reason_and_sort_by_independent_score(self):
        findings = [{**FINDING, "score": score, "score_reason": "影响广且正常操作可触发", "impact": f"影响{score}"}
                    for score in (81, 98, 89, 90)]
        body, _, _ = parse_result(json.dumps({"summary": "结论", "findings": findings, "verification": []}))
        self.assertIn("危险度 98/100", body)
        self.assertIn("评分理由：影响广", body)
        summary = summarize(body)
        self.assertLess(summary.index("98分"), summary.index("90分"))
        self.assertLess(summary.index("90分"), summary.index("89分"))
        self.assertNotIn("81分", summary)

    def test_aggregate_sorts_by_actual_score(self):
        from unittest.mock import patch
        import batch_review
        data = {"summary": "结论", "findings": [
            {**FINDING, "score": score, "score_reason": "有证据", "impact": f"分数{score}"}
            for score in (81, 98)], "verification": []}
        with patch.object(batch_review, "collect_context", return_value=("", [], {})), \
                patch.object(batch_review, "review_data", return_value=(data, [], "OPENAI")):
            body, _, _, _ = batch_review.review_batches([("diff", [])], "a" * 40)
        self.assertLess(body.index("危险度 98/100"), body.index("危险度 81/100"))

    def test_legacy_results_are_explicitly_reference_scores(self):
        body, _, _ = parse_result(json.dumps({"summary": "结论", "findings": [FINDING], "verification": []}))
        self.assertIn("模型未提供独立评分", body)
        self.assertIn("90分（等级参考）", summarize(body))
