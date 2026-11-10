"""稳定工作流的扩展入口；JSON 仅允许非密钥配置，不改运行元数据。"""

import json
import os

# 新配置在工具端加入这里，业务工作流无需新增 env 映射。
OPTIONS = {
    "block_on_risk": "AI_REVIEW_BLOCK_ON_RISK",
    "dingtalk_keyword": "AI_REVIEW_DINGTALK_KEYWORD",
    "openai_model": "AI_REVIEW_OPENAI_MODEL",
    "openai_base_url": "AI_REVIEW_OPENAI_BASE_URL",
    "claude_model": "AI_REVIEW_CLAUDE_MODEL",
    "claude_base_url": "AI_REVIEW_CLAUDE_BASE_URL",
}


def load_settings() -> None:
    """JSON 显式值覆盖单项 Variables；未设置值继续使用工具默认值。"""
    raw = os.getenv("AI_REVIEW_OPTIONS_JSON", "").strip()
    if not raw:
        return
    if len(raw.encode("utf-8")) > 16_000:
        raise ValueError("扩展配置超过大小限制")
    values = json.loads(raw)
    if not isinstance(values, dict) or any(key not in OPTIONS for key in values):
        raise ValueError("扩展配置包含未知字段")
    updates = {}
    for key, value in values.items():
        if key == "block_on_risk" and type(value) is bool:
            value = str(value).lower()
        if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
            raise ValueError("扩展配置值无效")
        updates[OPTIONS[key]] = value
    os.environ.update(updates)


def policy() -> int:
    """最后单独执行，避免模型步骤的容错吞掉已启用的风险阻断。"""
    try:
        load_settings()
        block = os.getenv("AI_REVIEW_BLOCK_ON_RISK", "").strip() or "false"
        if block not in {"true", "false"}:
            raise ValueError("阻断开关无效")
    except (ValueError, TypeError):
        print("审查配置无效，请检查阻断开关或扩展 JSON（不回显配置内容）。")
        return 1
    if block == "true" and os.getenv("AI_REVIEW_HAS_RISK", "") == "true":
        print("发现明确问题，按仓库配置标记任务失败。")
        return 1
    print("未触发风险阻断。")
    return 0
