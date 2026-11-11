"""多批聚合不丢风险、不重复通知的离线契约。"""

import os
import unittest
from unittest.mock import patch

import batch_review
from test_notify import FINDING


def data(findings=None, suggestions=None, verification=None):
    return {"summary": "本批结论", "findings": findings or [],
            "suggestions": suggestions or [], "verification": verification or []}


class BatchReviewTests(unittest.TestCase):
    def test_more_than_forty_findings_have_one_section_and_no_loss(self):
        first = [{**FINDING, "impact": f"问题{i}", "severity": "medium"} for i in range(40)]
        last = [{**FINDING, "impact": f"问题{i}"} for i in range(40, 47)]
        with patch.object(batch_review, "collect_context", return_value=("", [], {})), \
                patch.object(batch_review, "review_data", side_effect=[(data(first), [], "OPENAI"), (data(last), [], "OPENAI")]):
            text, _, _, _ = batch_review.review_batches([("a", []), ("b", [])], "a" * 40)
        for heading in ("## 总体结论", "## 明确问题", "## 改进建议", "## 待确认事项"):
            self.assertEqual(text.count(heading), 1)
        self.assertEqual(text.count("### "), 47)
        self.assertLess(text.index("影响：问题40"), text.index("影响：问题0\n"))

    def test_shared_plan_reused_without_replacing_numbered_rules(self):
        with patch.object(batch_review, "collect_context", return_value=("--- DOCUMENT: AGENTS.md (1 lines) ---\n1: 原文", [], {"AGENTS.md": 1})), \
                patch.object(batch_review, "review_data", return_value=(data(), [], "OPENAI")) as review:
            batch_review.review_batches([("a", []), ("b", [])], "a" * 40, "业务规划")
        self.assertEqual(review.call_count, 2)
        for call in review.call_args_list:
            self.assertIn("业务规划", call.args[1])
            self.assertIn("1: 原文", call.args[1])
            self.assertLess(call.args[1].index("业务规划"), call.args[1].index("--- DOCUMENT:"))

    def test_merge_dedup_and_independent_module_context(self):
        with patch.object(batch_review, "collect_context", side_effect=[("规范A", [], {}), ("规范B", [], {})]) as context, \
                patch.object(batch_review, "review_data", side_effect=[
                    (data([FINDING], ["建议"], ["确认"]), [], "OPENAI"),
                    (data([FINDING], ["建议"], ["确认"]), [], "CLAUDE")]) as review:
            text, notes, risk, notify = batch_review.review_batches([("diffA", ["a/x.py"]), ("diffB", ["b/x.py"])], "a" * 40)
        self.assertTrue(risk and notify)
        self.assertEqual(text.count("### high"), 1)
        self.assertIn("2/2", text)
        self.assertEqual(context.call_args_list[0].args[1], ["a/x.py"])
        self.assertEqual(review.call_args_list[1].args, ("diffB", "规范B", {}))
        self.assertIn("跨批", notes[0])

    def test_notify_threshold_keeps_risk_and_full_report(self):
        low = {**FINDING, "severity": "low"}
        with patch.dict(os.environ, {"AI_REVIEW_NOTIFY_LEVEL": "high"}), \
                patch.object(batch_review, "collect_context", return_value=("", [], {})), \
                patch.object(batch_review, "review_data", return_value=(data([low], ["建议"], ["确认"]), [], "OPENAI")):
            text, notes, risk, notify = batch_review.review_batches([("diff", [])], "a" * 40)
        self.assertTrue(risk)
        self.assertFalse(notify)
        self.assertIn("### low", text)
        self.assertIn("建议", text)
        self.assertTrue(any("未达到门槛" in note for note in notes))

    def test_failed_batch_does_not_erase_successful_risk(self):
        with patch.object(batch_review, "collect_context", return_value=("", [], {})), \
                patch.object(batch_review, "review_data", side_effect=[
                    (data([FINDING]), [], "OPENAI"), (None, ["失败"], "")]):
            text, notes, risk, notify = batch_review.review_batches([("a", []), ("b", [])], "a" * 40)
        self.assertTrue(risk and notify)
        self.assertIn("1/2", text)
        self.assertTrue(any("覆盖不完整" in note for note in notes))

    def test_batch_environment_failure_preserves_prior_risk(self):
        with patch.object(batch_review, "collect_context", side_effect=[("", [], {}), OSError("private")]), \
                patch.object(batch_review, "review_data", return_value=(data([FINDING]), [], "OPENAI")):
            text, notes, risk, notify = batch_review.review_batches([("a", []), ("b", [])], "a" * 40)
        self.assertTrue(risk and notify)
        self.assertIn("1/2", text)
        self.assertNotIn("private", "".join(notes))

    def test_all_failed_no_safe_claim_and_no_notification(self):
        with patch.object(batch_review, "collect_context", return_value=("", [], {})), \
                patch.object(batch_review, "review_data", return_value=(None, [], "")):
            text, _, risk, notify = batch_review.review_batches([("a", [])], "a" * 40)
        self.assertFalse(risk or notify)
        self.assertIn("审查未完成", text)

    def test_deadline_stops_new_requests(self):
        with patch.object(batch_review.time, "monotonic", side_effect=[0, 901]), \
                patch.object(batch_review, "review_data") as review:
            text, notes, _, _ = batch_review.review_batches([("a", [])], "a" * 40)
        review.assert_not_called()
        self.assertIn("0/1", text)
        self.assertTrue(any("启动预算" in note for note in notes))

    def test_budget_rejects_oversized_request(self):
        with patch.object(batch_review, "review_data") as review:
            _, notes, _, _ = batch_review.review_batches([("x" * 200000, [])], "a" * 40)
        review.assert_not_called()
        self.assertTrue(any("超过输入预算" in note for note in notes))

    def test_more_than_40_findings_are_kept(self):
        items = [dict(FINDING, line=str(i)) for i in range(41)]
        with patch.object(batch_review, "collect_context", return_value=("", [], {})), \
                patch.object(batch_review, "review_data", side_effect=[
                    (data(items[:40]), [], "OPENAI"), (data(items[40:]), [], "OPENAI")]):
            text, _, risk, _ = batch_review.review_batches([("a", []), ("b", [])], "a" * 40)
        self.assertTrue(risk)
        self.assertEqual(text.count("### high"), 41)


if __name__ == "__main__":
    unittest.main()
