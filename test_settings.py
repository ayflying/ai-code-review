"""固定工作流的后台配置与最终策略离线测试。"""

import os
import unittest
from unittest.mock import patch

from settings import limit_value, load_settings, policy


class SettingsTests(unittest.TestCase):
    def test_policy_matrix(self):
        for block in ("true", "false", ""):
            for risk in ("true", "false", ""):
                with patch.dict(os.environ, {"AI_REVIEW_BLOCK_ON_RISK": block,
                                            "AI_REVIEW_HAS_RISK": risk}, clear=True):
                    self.assertEqual(policy(), int(block == "true" and risk == "true"))

    def test_json_overrides_plain_variables_without_secrets(self):
        with patch.dict(os.environ, {"AI_REVIEW_OPTIONS_JSON": '{"block_on_risk":true,"openai_model":"test"}',
                                    "AI_REVIEW_BLOCK_ON_RISK": "false", "AI_REVIEW_HAS_RISK": "true"}, clear=True):
            load_settings()
            self.assertEqual(os.environ["AI_REVIEW_OPENAI_MODEL"], "test")
            self.assertEqual(policy(), 1)

    def test_unknown_keys_and_invalid_values_fail_without_partial_updates(self):
        for raw in ('{"api_key":"secret"}', '{"tool_ref":"main"}', '[]', '{bad',
                    '{"openai_model":"ok","block_on_risk":null}', '{"openai_model":12}',
                    '{"openai_model":"bad\\nvalue"}', 'x' * 16001):
            with patch.dict(os.environ, {"AI_REVIEW_OPTIONS_JSON": raw}, clear=True):
                self.assertEqual(policy(), 1)
                self.assertNotIn("AI_REVIEW_OPENAI_MODEL", os.environ)

    def test_batch_limits_defaults_and_json_numbers(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(limit_value("AI_REVIEW_MAX_BATCHES"), 20)
            self.assertEqual(limit_value("AI_REVIEW_MAX_FILES"), 300)
            self.assertEqual(limit_value("AI_REVIEW_BATCH_BYTES"), 100000)
            self.assertEqual(limit_value("AI_REVIEW_INPUT_BYTES"), 160000)
        with patch.dict(os.environ, {"AI_REVIEW_OPTIONS_JSON": '{"max_batches":40,"max_files":600,"batch_bytes":200000,"input_bytes":300000}'}, clear=True):
            load_settings()
            self.assertEqual(limit_value("AI_REVIEW_MAX_BATCHES"), 40)
            self.assertEqual(limit_value("AI_REVIEW_BATCH_BYTES"), 200000)
            self.assertEqual(policy(), 0)

    def test_invalid_batch_limit_fails_policy(self):
        for value in ("0", "-1", "1.5", "true", "201", "９"):
            with patch.dict(os.environ, {"AI_REVIEW_MAX_BATCHES": value}, clear=True):
                self.assertEqual(policy(), 1)

    def test_invalid_block_switch_fails(self):
        with patch.dict(os.environ, {"AI_REVIEW_BLOCK_ON_RISK": "yes"}, clear=True):
            self.assertEqual(policy(), 1)


if __name__ == "__main__":
    unittest.main()
