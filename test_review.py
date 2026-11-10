"""不使用真实凭据或网络的独立契约测试。"""

import json
import os
import unittest
from unittest.mock import patch

import changes
import providers
import run


EMPTY_REPORT = json.dumps({"summary": "中文报告", "findings": [], "verification": []}, ensure_ascii=False)


class ReviewTests(unittest.TestCase):
    def test_missing_key_skips_all_work(self):
        for value in ("", "  "):
            with patch.dict(os.environ, {"AI_REVIEW_OPENAI_API_KEY": value}), \
                    patch.object(run, "collect_batches") as collect, \
                    patch.object(run, "review_batches") as review:
                self.assertEqual(run.main(), 0)
                collect.assert_not_called()
                review.assert_not_called()

    def test_prompt_focuses_on_business_not_reviewer_operations(self):
        self.assertIn("审查目标是被审业务项目", providers.SYSTEM)
        self.assertIn("不提出锁定工具标签或调整工具参数的计划", providers.SYSTEM)
        self.assertIn("实际秘密泄露、越权执行或破坏业务构建发布", providers.SYSTEM)
        self.assertIn("返回空问题/建议/待确认数组", providers.SYSTEM)

    def test_primary_success_does_not_call_backup(self):
        with patch.object(providers, "review", return_value=EMPTY_REPORT) as review:
            text, notes, has_risk = providers.review_with_fallback("diff")
            self.assertFalse(has_risk)
            review.assert_called_once_with("OPENAI", "diff")
            self.assertIn("OPENAI", text)
            self.assertEqual(notes, [])

    def test_primary_failure_uses_backup(self):
        with patch.object(providers, "review", side_effect=[providers.ReviewError("超时"), EMPTY_REPORT]) as review:
            text, notes, has_risk = providers.review_with_fallback("diff")
            self.assertFalse(has_risk)
            self.assertEqual(review.call_args_list[1].args, ("CLAUDE", "diff"))
            self.assertIn("CLAUDE", text)
            self.assertIn("超时", notes[0])

    def test_both_failed_explicitly_incomplete(self):
        with patch.object(providers, "review", side_effect=providers.ReviewError("失败")):
            text, notes, has_risk = providers.review_with_fallback("diff")
            self.assertFalse(has_risk)
            self.assertIn("审查未完成", text)
            self.assertEqual(len(notes), 2)

    def test_openai_responses_contract(self):
        with patch.dict(os.environ, {"AI_REVIEW_OPENAI_API_KEY": "fake", "AI_REVIEW_OPENAI_MODEL": "model"}), \
                patch.object(providers, "request_json", return_value={
                    "status": "completed", "output": [{"type": "message", "content": [
                        {"type": "output_text", "text": "风险报告"}]}]}) as request:
            self.assertEqual(providers.review("OPENAI", "diff"), "风险报告")
            self.assertTrue(request.call_args.args[0].endswith("/responses"))
            self.assertFalse(request.call_args.args[2]["store"])

    def test_claude_messages_contract(self):
        with patch.dict(os.environ, {"AI_REVIEW_CLAUDE_API_KEY": "fake", "AI_REVIEW_CLAUDE_MODEL": "model"}), \
                patch.object(providers, "request_json", return_value={
                    "stop_reason": "end_turn", "content": [{"type": "text", "text": "报告"}]}) as request:
            self.assertEqual(providers.review("CLAUDE", "diff"), "报告")
            self.assertTrue(request.call_args.args[0].endswith("/messages"))
            self.assertEqual(request.call_args.args[1]["anthropic-version"], "2023-06-01")

    def test_incomplete_response_rejected(self):
        with patch.dict(os.environ, {"AI_REVIEW_OPENAI_API_KEY": "fake", "AI_REVIEW_OPENAI_MODEL": "model"}), \
                patch.object(providers, "request_json", return_value={"status": "incomplete"}):
            with self.assertRaises(providers.ReviewError):
                providers.review("OPENAI", "diff")

    def test_git_push_uses_before_after(self):
        before, after = "a" * 40, "b" * 40
        with patch.dict(os.environ, {"AI_REVIEW_BEFORE": before, "AI_REVIEW_AFTER": after}), \
                patch.object(changes, "git", side_effect=[b"ok", b"ok", b"src/main.py\0.env\0", b"diff content"]) as git:
            text, notes = changes.collect()
            self.assertEqual(text, "diff content")
            self.assertIn(before, notes[0])
            self.assertIn("覆盖不完整", notes[1])
            self.assertIn(before, git.call_args.args)
            self.assertIn(after, git.call_args.args)
            self.assertIn("--no-textconv", git.call_args.args)

    def test_missing_before_does_not_silently_fallback(self):
        with patch.dict(os.environ, {"AI_REVIEW_BEFORE": "a" * 40, "AI_REVIEW_AFTER": "b" * 40}), \
                patch.object(changes, "git", side_effect=[b"ok", ValueError("missing")]) as git:
            with self.assertRaises(ValueError):
                changes.collect()
            self.assertEqual(git.call_count, 2)

    def test_sensitive_paths(self):
        for path in (".env", "config/.env.production", "keys/client.pem", "secrets/key.txt"):
            self.assertTrue(changes.sensitive(path))
        self.assertFalse(changes.sensitive("src/main.py"))

    def test_endpoint_rejects_unsafe_addresses(self):
        for base in ("http://example.com/v1", "https://user:password@example.com", "https://example.com?x=1"):
            with self.assertRaises(providers.ReviewError):
                providers.endpoint(base, "/responses")

    def test_report_neutralizes_commands_and_keys(self):
        with patch.dict(os.environ, {"AI_REVIEW_OPENAI_API_KEY": "fake-secret"}):
            text = run.sanitize("::warning::fake-secret\n\x1b[31mtest")
            self.assertNotIn("fake-secret", text)
            self.assertNotIn("\x1b", text)
            self.assertTrue(all(line.startswith("报告 | ") for line in text.splitlines()))


if __name__ == "__main__":
    unittest.main()
