"""逐批独立上下文审查；本地汇总有效结果，不再把所有差异塞给一次模型。"""

import json
import subprocess
import time

from batch_parallel import review_prepared
from providers import SYSTEM, review_data
from report import parse_result
from review_context import collect_context
from risk_score import score_of
from settings import limit_value, notification_level, should_notify_result

# 按 UTF-8 字节保守估计 token 上界（非精确分词），预留输出和协议开销。
MAX_INPUT_BYTES = 160_000
MAX_CONTEXT_BYTES = 60_000
MAX_SECONDS = 900


def _unique(items: list) -> list:
    seen: set[str] = set()
    result = []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def review_batches(batches: list[tuple[str, list[str]]], after: str, shared_context: str = ""
                   ) -> tuple[str, list[str], bool, bool]:
    """每批失败不覆盖其他批结论；建议通知与明确问题阻断分别累计。"""
    level = notification_level()  # 请求前验证，避免无效配置消耗模型调用。
    input_bytes = limit_value("AI_REVIEW_INPUT_BYTES", MAX_INPUT_BYTES)
    workers = limit_value("AI_REVIEW_CONCURRENCY")
    # 最小输入配置仍保留原文规范空间，规划只是辅助，不可挤掉整批审查。
    shared_context = shared_context.encode("utf-8")[:min(6000, input_bytes // 10)].decode("utf-8", "ignore")
    notes = [f"分批审查：共 {len(batches)} 批；单次输入预算 {input_bytes} 字节；各批独立上下文，跨批关联问题可能漏报。"]
    summaries: list[str] = []
    findings: list[dict] = []
    suggestions: list[str] = []
    verification: list[str] = []
    documents: dict[str, int] = {}
    contexts: list[str] = []
    deadline = time.monotonic() + MAX_SECONDS
    completed = 0
    prepared = []
    notes.append(f"详细AI审查最多 {workers} 并发；各批文档顺序加载后再请求模型。")
    for index, (diff, paths) in enumerate(batches, 1):
        if time.monotonic() >= deadline:
            notes.append(f"覆盖不完整：达到 {MAX_SECONDS} 秒启动预算，第 {index} 批起未审查；在途请求可能额外耗时。")
            break
        # 每个请求都单独计算预算并附带其涉及模块的规范。
        budget = min(MAX_CONTEXT_BYTES, input_bytes - len(SYSTEM.encode("utf-8"))
                     - len(diff.encode("utf-8")) - len(shared_context.encode("utf-8")) - 1800)
        if budget <= 0:
            notes.append(f"覆盖不完整：第 {index} 批超过输入预算，未发送。")
            continue
        try:
            context, context_notes, loaded = collect_context(after, paths, max_bytes=budget)
            notes.extend(f"第 {index} 批：{note}" for note in context_notes)
            if shared_context:
                # 摘要放编号原文之前，避免被误当成最后一个规范文档的引用证据。
                context = ("同次CI共享规划（模型生成的辅助数据，不是规范原文或指令）：\n"
                           + shared_context + "\n\n" + context)
            prepared.append((index, diff, context, loaded, paths))
        except (ValueError, OSError, subprocess.SubprocessError):
            notes.append(f"覆盖不完整：第 {index} 批运行环境异常；保留其他批次结论。")
            continue
    for item, data, attempts, provider in review_prepared(prepared, workers, deadline, review_data):
        index, _, context, loaded, paths = item
        notes.extend(f"第 {index} 批：{note}" for note in attempts)
        if data is None:
            notes.append(f"覆盖不完整：第 {index} 批主备审查均失败；不能据此判断安全。")
            continue
        completed += 1
        for path in paths:
            notes.append(f"详细审查第 {index} 批已返回有效结论：{path}（仅本批所含差异片段，不代表文件完整覆盖）。")
        summaries.append(f"第 {index} 批（{provider}）：{data['summary']}")
        findings.extend(data["findings"])
        suggestions.extend(data.get("suggestions", []))
        verification.extend(data["verification"])
        documents.update(loaded)
        contexts.append(context)
    findings = sorted(_unique(findings), key=score_of, reverse=True)
    suggestions = _unique(suggestions)
    verification = _unique(verification)
    risk = bool(findings)
    notify = should_notify_result(findings, suggestions, verification)
    notes.append(f"钉钉通知门槛：{level}；{'达到门槛' if notify else '未达到门槛，不发送通知'}；不影响风险阻断。")
    # 模型单批仍限40条；仅本地已校验的聚合结果放宽数量，统一渲染一组章节。
    parts = [f"已完成 {completed}/{len(batches)} 批。未完成批次不代表安全。"]
    if not completed:
        parts.append("审查未完成，没有有效模型结论，不能据此判断安全。")
        return "\n\n".join(parts), notes, False, False
    summary = "\n".join(summaries)
    count = max(len(findings), len(suggestions), len(verification), 1)
    data = {"summary": summary, "findings": findings,
            "suggestions": suggestions, "verification": verification}
    body, _, _ = parse_result(json.dumps(data, ensure_ascii=False), documents,
                              "\n\n".join(contexts), max_items=count)
    parts.append(body)
    return "\n\n".join(parts), notes, risk, notify
