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
    "max_batches": "AI_REVIEW_MAX_BATCHES",
    "max_files": "AI_REVIEW_MAX_FILES",
    "batch_bytes": "AI_REVIEW_BATCH_BYTES",
    "input_bytes": "AI_REVIEW_INPUT_BYTES",
}

LIMITS = {
    "AI_REVIEW_MAX_BATCHES": (20, 1, 200),
    "AI_REVIEW_MAX_FILES": (300, 1, 5000),
    "AI_REVIEW_BATCH_BYTES": (100000, 1000, 1000000),
    "AI_REVIEW_INPUT_BYTES": (160000, 10000, 2000000),
}


def limit_value(name: str, default: int | None = None) -> int:
    """正整数配置限制；批大小保留输入及规范预算，不允许无限放大。"""
    fallback, minimum, maximum = LIMITS[name]
    raw = os.getenv(name, "").strip() or str(fallback if default is None else default)
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 6:
        raise ValueError("分批限制必须为正整数")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ValueError("分批限制超出允许范围")
    return value


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
        if OPTIONS[key] in LIMITS and type(value) is int:
            value = str(value)
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
        for name in LIMITS:
            limit_value(name)
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
