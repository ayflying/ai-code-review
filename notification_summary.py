"""从已校验的报告提取短消息，不额外调用模型，不复制覆盖日志。"""

import re


def short_text(value: str, limit: int = 100) -> str:
    """清理 Markdown 和控制字符，避免模型内容改变通知布局。"""
    value = re.sub(r"[\x00-\x1f\x7f\[\]<>`*_#]", " ", value)
    value = " ".join(value.split())
    return value[:limit] + ("…" if len(value) > limit else "")


def summarize(report: str) -> str:
    """计数来自本地已渲染契约；只展示前两项影响，不重述长篇模型总结。"""
    lines = [line.removeprefix("报告 | ").strip() for line in report.splitlines()]
    counts = {"明确问题": 0, "改进建议": 0, "待确认事项": 0}
    points = []
    section = ""
    location = ""
    for line in lines:
        if line.startswith("## "):
            section = line[3:]
        elif section == "明确问题" and re.match(r"### (high|medium|low) \|", line):
            counts[section] += 1
            location = line.split(" | ", 2)[-1]
        elif section == "明确问题" and line.startswith("影响：") and len(points) < 2:
            points.append(f"- {short_text(location, 70)}：{short_text(line[3:], 100)}")
        elif section in {"改进建议", "待确认事项"} and line and line != "无。":
            counts[section] += 1
    result = [" / ".join(f"{name} {number} 项" for name, number in counts.items())]
    result.extend(points)
    if not points:
        result.append("有建议或待确认事项，请查看详情。")
    if "覆盖不完整" in report or "审查未完成" in report or "未完成批次：" in report:
        result.append("部分内容未覆盖，范围说明见详情。")
    return "\n\n".join(result)
