"""规范清单读取失败原因需可区分，且不能泄露原始错误。"""

import subprocess
import unittest
from unittest.mock import patch

from changes import GitOutputLimitError, GitReadError
from review_context import collect_context


class ContextErrorTests(unittest.TestCase):
    def test_distinct_failure_reasons_without_raw_error(self):
        cases = [
            (GitOutputLimitError("PRIVATE"), "超过 1,000,000 字节读取上限"),
            (subprocess.TimeoutExpired("PRIVATE", 45), "Git 读取超时"),
            (GitReadError("PRIVATE"), "Git 命令执行失败"),
            (OSError("PRIVATE"), "无法启动 Git 或访问本机读取资源"),
            (ValueError("PRIVATE"), "Git 返回的数据无效"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected), patch("review_context.git", side_effect=error):
                text, notes, docs = collect_context("a" * 40, [])
            self.assertEqual(text, "")
            self.assertEqual(docs, {})
            self.assertIn(expected, notes[0])
            self.assertIn("代码差异审查继续", notes[0])
            self.assertNotIn("PRIVATE", notes[0])
            self.assertNotIn("失败或超限", notes[0])
