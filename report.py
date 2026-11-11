"""结构化结果分别决定风险阻断和消息通知，不猜测自然语言关键词。"""

import json
import re

CONTRACT = """
只返回一个 JSON 对象，不要 Markdown 围栏。字段：
summary: 中文总体结论；findings: 明确问题数组；suggestions: 中文改进建议字符串数组；
verification: 中文待确认事项字符串数组。没有内容时对应数组为 []。
每条 findings 必须包含非空字符串 severity（high/medium/low）、file、line、
condition（触发条件）、impact、evidence（变更证据，不含秘密）、suggestion（修复建议）。
kind 为 risk（实际代码风险）或 policy（明确违反项目规范）。
policy 必须另含 rule_file（已提供的规范路径）、rule_line（规范行号字符串）、
rule（该行开始的原文引用）。规则须适用于该变更，且有明确违反证据；
格式、命名等普通建议放 suggestions，不得夸大为明确问题。
不确定、规范冲突、缺少上下文的事项只放 verification，不编造规范或问题。
"""


def parse_result(text: str, documents: dict[str, int] | None = None,
                 context: str = "", *, max_items: int = 40) -> tuple[str, bool, bool]:
    """校验规范引用确实来自已加载文档；不把建议或待确认项算成风险。"""
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("无效总体结论")
    findings = data.get("findings")
    verification = data.get("verification")
    suggestions = data.get("suggestions", [])
    if not isinstance(findings, list):
        raise ValueError("无效问题数组")
    for items in (verification, suggestions):
        if not isinstance(items, list) or len(items) > max_items or not all(
            isinstance(item, str) and item.strip() for item in items
        ):
            raise ValueError("无效建议或待确认事项")
    if len(findings) > max_items:
        raise ValueError("问题过多")
    lines = ["## 总体结论", data["summary"], "", "## 明确问题"]
    for finding in findings:
        fields = ("severity", "file", "line", "condition", "impact", "evidence", "suggestion")
        if not isinstance(finding, dict) or any(
            not isinstance(finding.get(key), str) or not finding[key].strip() for key in fields
        ) or finding["severity"] not in {"high", "medium", "low"}:
            raise ValueError("无效问题条目")
        kind = finding.get("kind", "risk")
        if kind not in {"risk", "policy"}:
            raise ValueError("无效问题类型")
        label = "代码风险" if kind == "risk" else "违反项目规范"
        lines.extend([
            f"### {finding['severity']} | {label} | {finding['file']}:{finding['line']}",
            f"触发条件：{finding['condition']}", f"影响：{finding['impact']}",
            f"变更证据：{finding['evidence']}",
        ])
        if kind == "policy":
            source, number, quote = (finding.get(key) for key in ("rule_file", "rule_line", "rule"))
            if (not isinstance(source, str) or source not in (documents or {})
                    or not isinstance(number, str) or not re.fullmatch(r"[1-9][0-9]{0,5}", number)
                    or int(number) > documents[source]
                    or not isinstance(quote, str) or not quote.strip()):
                raise ValueError("无效规范引用")
            # 路径与行数只能证明来源存在，具体原文校验由上下文的逐行记录完成。
            from review_context import source_line
            original = source_line(context, source, int(number))
            if not original or quote.strip() not in original:
                raise ValueError("规范原文不匹配")
            lines.append(f"规范依据：{source}:{number} — {quote}")
        lines.extend([f"修复建议：{finding['suggestion']}", ""])
    if not findings:
        lines.append("在已提供的变更范围内未发现明确问题，不代表整个提交安全。")
    lines.extend(["", "## 改进建议", *(suggestions or ["无。"]),
                  "", "## 待确认事项", *(verification or ["无。"])])
    return "\n".join(lines), bool(findings), bool(findings or suggestions or verification)


def parse_report(text: str) -> tuple[str, bool]:
    """兼容仅需风险状态的原调用者。"""
    body, risk, _ = parse_result(text)
    return body, risk
