"""通知与结构化判定测试，不向真实群发送虚构风险。"""

import json
import os
import unittest
from unittest.mock import patch

import notify
import providers
from report import parse_report

WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=fake-test-token"
FINDING = {"severity": "high", "file": "src/example.py", "line": "12",
           "condition": "未授权调用", "impact": "越权", "evidence": "缺少权限判断", "suggestion": "补充鉴权"}


def result(findings):
    return json.dumps({"summary": "审查结论", "findings": findings, "verification": []}, ensure_ascii=False)


class NotifyTests(unittest.TestCase):
    def test_all_high_findings_before_medium_and_paginated_with_keyword(self):
        from notification_summary import summarize
        report = "## 明确问题\n### medium | 代码风险\n影响：中风险\n" + "\n".join(
            f"### high | 代码风险\n影响：严重{i:03d} " + "中" * 100 for i in range(80))
        summary = summarize(report)
        self.assertLess(summary.index("严重000"), summary.index("中风险"))
        self.assertIn("90分", summary)
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": WEBHOOK, "AI_REVIEW_DINGTALK_KEYWORD": "gitea"}), \
                patch.object(notify, "request_json", return_value={"errcode": 0}) as request:
            self.assertIn("已接受", notify.notify_risk(report, True))
        self.assertGreater(request.call_count, 1)
        messages = [call.args[2]["markdown"]["text"] for call in request.call_args_list]
        for message in messages:
            self.assertIn("gitea", message)
            self.assertLessEqual(len(message.encode("utf-8")), 16000)
        for index in range(80):
            self.assertEqual("\n".join(messages).count(f"严重{index:03d}"), 1)

    def test_no_risk_never_sends(self):
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": WEBHOOK}), \
                patch.object(notify, "request_json") as request:
            notify.notify_risk("包含风险二字也不能触发", False)
            request.assert_not_called()

    def test_risk_requires_webhook(self):
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": ""}), \
                patch.object(notify, "request_json") as request:
            self.assertIn("未配置", notify.notify_risk("风险", True))
            request.assert_not_called()

    def test_risk_sends_keyword_and_context(self):
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": WEBHOOK,
                                    "AI_REVIEW_REPOSITORY": "owner/repo",
                                    "AI_REVIEW_AFTER": "abc", "AI_REVIEW_COMMIT_SUBJECT": "修复素材列表筛选",
                                     "AI_REVIEW_RUN_URL": "https://git.example/run/1"}), \
                patch.object(notify, "request_json", return_value={"errcode": 0}) as request:
            self.assertIn("已接受", notify.notify_risk("风险" * 12000, True))
            payload = request.call_args.args[2]
            text = payload["markdown"]["text"]
            self.assertIn("gitea", text)
            self.assertTrue(text.startswith("# owner/repo\n"))
            self.assertTrue(payload["markdown"]["title"].startswith("owner/repo ·"))
            self.assertIn("本次提交：修复素材列表筛选", text)
            self.assertIn("https://git.example/run/1", text)
            self.assertNotIn("截断", text)
            self.assertNotIn("风险" * 20, text)
            self.assertIn("查看问题详细报告", text)
            self.assertLess(len(text.encode()), 2000)

    def test_concise_summary_counts_and_skips_coverage_logs(self):
        from notification_summary import summarize
        report = "覆盖不完整：缺少README\n" + parse_report(result([FINDING]))[0]
        text = summarize(report)
        self.assertIn("明确问题 1 项", text)
        self.assertIn("改进建议 0 项", text)
        self.assertIn("🔴 严重问题", text)
        self.assertIn("越权", text)
        self.assertNotIn("src/example.py", text)
        self.assertNotIn("缺少README", text)
        self.assertNotIn("触发条件", text)

    def test_custom_keyword(self):
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": WEBHOOK,
                                    "AI_REVIEW_DINGTALK_KEYWORD": "代码告警"}), \
                patch.object(notify, "request_json", return_value={"errcode": 0}) as request:
            notify.notify_risk("报告", True)
            payload = request.call_args.args[2]["markdown"]
            self.assertIn("代码告警", payload["title"])
            self.assertIn("代码告警", payload["text"])

    def test_invalid_keyword_does_not_send(self):
        for keyword in ("", "\n", "字" * 201):
            with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": WEBHOOK,
                                        "AI_REVIEW_DINGTALK_KEYWORD": keyword}), \
                    patch.object(notify, "request_json") as request:
                self.assertIn("无效", notify.notify_risk("报告", True))
                request.assert_not_called()

    def test_robot_rejection_not_success(self):
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": WEBHOOK}), \
                patch.object(notify, "request_json", return_value={"errcode": 310000, "errmsg": "sensitive"}):
            message = notify.notify_risk("报告", True)
            self.assertIn("拒绝", message)
            self.assertNotIn("sensitive", message)

    def test_network_error_no_leak_or_retry(self):
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": WEBHOOK}), \
                patch.object(notify, "request_json", side_effect=providers.ReviewError("失败")) as request:
            self.assertIn("状态未知", notify.notify_risk("报告", True))
            request.assert_called_once()

    def test_bad_host_never_sends(self):
        with patch.dict(os.environ, {"AI_REVIEW_DINGTALK_WEBHOOK": "https://evil.example/robot/send?access_token=x"}), \
                patch.object(notify, "request_json") as request:
            self.assertIn("无效", notify.notify_risk("报告", True))
            request.assert_not_called()

    def test_structured_risk_and_no_risk(self):
        self.assertTrue(parse_report(result([FINDING]))[1])
        self.assertFalse(parse_report(result([]))[1])

    def test_malformed_risk_rejected(self):
        for value in ("不是JSON", result([{}]), result([{"severity": "high"}])):
            with self.assertRaises(ValueError):
                parse_report(value)

    def test_invalid_primary_structure_falls_back(self):
        with patch.object(providers, "review", side_effect=["普通Markdown", result([FINDING])]):
            text, notices, risk = providers.review_with_fallback("diff")
            self.assertTrue(risk)
            self.assertIn("CLAUDE", text)
            self.assertIn("响应结构异常", notices[0])


if __name__ == "__main__":
    unittest.main()
