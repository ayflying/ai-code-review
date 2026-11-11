"""不进行真实请求或等待的文件筛选重试测试。"""

import unittest
from unittest.mock import patch

import planning_retry as retry
import review_plan as plan
from test_review_plan import file, result


class RetryTests(unittest.TestCase):
    @patch.object(retry.time, "sleep")
    def test_five_retries_then_claude_fallback(self, sleep):
        files = [file("a")]
        errors = [retry.providers.ReviewError(retry.TIMEOUT_MESSAGE) for _ in range(6)]
        with patch.object(retry.providers, "planning_request", side_effect=errors + [result(files)]) as request:
            selected, _, notes = plan.plan_files(files, "", 10000)
        self.assertEqual(selected, {"a"})
        self.assertEqual([c.args[0] for c in request.call_args_list], ["OPENAI"] * 6 + ["CLAUDE"])
        self.assertEqual(sleep.call_count, 5)
        self.assertIn("首次请求及5次重试均超时", "\n".join(notes))
        self.assertIn("CLAUDE 已成功", "\n".join(notes))

    @patch.object(retry.time, "sleep")
    def test_retry_success_stops_and_is_not_called_fallback(self, sleep):
        files = [file("a")]
        with patch.object(retry.providers, "planning_request", side_effect=[
                retry.providers.ReviewError(retry.TIMEOUT_MESSAGE), result(files)]) as request:
            _, _, notes = plan.plan_files(files, "", 10000)
        self.assertEqual(request.call_count, 2)
        self.assertIn("OPENAI 第 2 次请求成功", "\n".join(notes))
        self.assertNotIn("CLAUDE 已成功", "\n".join(notes))

    def test_authentication_failure_not_retried(self):
        with patch.object(retry.providers, "planning_request", side_effect=retry.providers.ReviewError("接口 HTTP 401")) as request:
            with self.assertRaises(retry.providers.ReviewError):
                retry.request_with_retries("OPENAI", "prompt", [])
        self.assertEqual(request.call_count, 1)
