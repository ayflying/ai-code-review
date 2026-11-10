"""结构化结果决定是否通知；不通过自然语言关键词猜测风险。"""

import json

CONTRACT = """
只返回一个 JSON 对象，不要 Markdown 围栏。字段：
summary: 中文总体结论字符串；findings: 风险数组；verification: 中文待验证事项字符串数组。
每条 findings 必须包含非空字符串 severity（只能 high/medium/low）、file、line、
condition（触发条件）、impact、evidence（代码证据，不含秘密）、suggestion（修复建议）。
只把有明确证据的实际问题放入 findings，无问题必须为 []；待验证猜测只放 verification。
"""


def parse_report(text: str) -> tuple[str, bool]:
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("无效总体结论")
    findings, verification = data.get("findings"), data.get("verification")
    if not isinstance(findings, list) or not isinstance(verification, list):
        raise ValueError("无效风险数组")
    if len(findings) > 40 or not all(isinstance(item, str) for item in verification):
        raise ValueError("无效待验证事项")
    lines = ["## 总体结论", data["summary"], "", "## 风险详情"]
    for finding in findings:
        fields = ("severity", "file", "line", "condition", "impact", "evidence", "suggestion")
        if not isinstance(finding, dict) or any(
            not isinstance(finding.get(key), str) or not finding[key].strip() for key in fields
        ) or finding["severity"] not in {"high", "medium", "low"}:
            raise ValueError("无效风险条目")
        lines.extend([
            f"### {finding['severity']} | {finding['file']}:{finding['line']}",
            f"触发条件：{finding['condition']}", f"影响：{finding['impact']}",
            f"代码证据：{finding['evidence']}", f"修复建议：{finding['suggestion']}", "",
        ])
    if not findings:
        lines.append("在已提供的变更范围内未发现明确风险。")
    lines.extend(["", "## 待验证事项", *verification])
    return "\n".join(lines), bool(findings)
