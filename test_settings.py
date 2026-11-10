"""固定工作流的后台配置与最终策略离线测试。"""

import os
import unittest
from unittest.mock import patch

from settings import load_settings, policy


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

    def test_invalid_block_switch_fails(self):
        with patch.dict(os.environ, {"AI_REVIEW_BLOCK_ON_RISK": "yes"}, clear=True):
            self.assertEqual(policy(), 1)


if __name__ == "__main__":
    unittest.main()
