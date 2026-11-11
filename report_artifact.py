"""生成静态报告：仅渲染本工具的报告结构，所有模型文本先转义。"""

import re
from html import escape
from pathlib import Path


STYLE = """
:root{color-scheme:light dark}
body{max-width:1050px;margin:32px auto;padding:0 24px;font:16px/1.8 system-ui;color:#243247;background:#fff}
h1{font-size:28px;margin-bottom:24px}h2{font-size:22px;margin:32px 0 16px;border-bottom:1px solid #dce3ed;padding-bottom:8px}
h3{font-size:17px;margin:24px 0 12px;padding:12px 16px;border-left:5px solid #64748b;background:#f1f5f9;border-radius:5px}
h3.high{border-color:#dc2626;color:#b91c1c;background:#fff1f2}h3.medium{border-color:#ea580c;color:#9a3412;background:#fff7ed}
h3.low{border-color:#ca8a04;color:#854d0e;background:#fefce8}p{margin:10px 0;overflow-wrap:anywhere}
.field{display:grid;grid-template-columns:90px minmax(0,1fr);gap:12px;margin:12px 0}
.field strong{color:#475569}code{background:#f1f5f9;padding:2px 5px;border-radius:4px}
details{margin-top:36px;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px}
summary{cursor:pointer;font-weight:600}
/* 静态产物无父页面DOM权限，通过浏览器/嵌入页传递的配色偏好适配夜间模式。 */
@media(prefers-color-scheme:dark){
body{color:#e2e8f0;background:#171e2b}h2{border-color:#475569}
h3{color:#e2e8f0;background:#273449;border-color:#94a3b8}
h3.high{color:#fda4af;background:#471c28;border-color:#fb7185}
h3.medium{color:#fdba74;background:#432c1b;border-color:#fb923c}
h3.low{color:#fde68a;background:#3b331a;border-color:#facc15}
.field strong{color:#cbd5e1}code{color:#e2e8f0;background:#273449}
details{color:#e2e8f0;background:#202b3c;border-color:#475569}
}
@media(max-width:600px){body{margin:16px auto;padding:0 14px}.field{display:block}.field strong{display:block}}
"""


def render_report(text: str) -> str:
    """支持报告标题、字段及普通段落；不解释原始HTML、链接或任意Markdown扩展。"""
    parts = []
    labels = {"触发条件", "影响", "变更证据", "修复建议", "规范依据", "评分理由"}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        heading = re.fullmatch(r"(#{1,3})\s+(.+)", line)
        if heading:
            depth, title = len(heading[1]), heading[2]
            severity = title.split(" | ", 1)[0]
            color = f' class="{severity}"' if depth == 3 and severity in {"high", "medium", "low"} else ""
            title = re.sub(r"^(high|medium|low)(?= \|)",
                           lambda m: {"high": "严重问题", "medium": "中等问题", "low": "轻微问题"}[m[0]], title)
            parts.append(f"<h{depth}{color}>{escape(title)}</h{depth}>")
            continue
        label, separator, value = line.partition("：")
        if separator and label in labels:
            parts.append(f'<div class="field"><strong>{escape(label)}</strong><div>{escape(value)}</div></div>')
        else:
            parts.append(f"<p>{escape(line)}</p>")
    return "\n".join(parts)


def write_report(directory: Path, report: str, notes: list[str]) -> Path:
    destination = directory / "ai-code-review-report"
    destination.mkdir(parents=True, exist_ok=True)
    markdown = report + "\n\n## 审查范围与覆盖说明\n\n" + "\n".join(notes)
    (destination / "report.md").write_text(markdown + "\n", encoding="utf-8")
    (destination / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        '<title>代码审查详细报告</title><style>' + STYLE + '</style></head><body>'
        '<h1>代码审查详细报告</h1>' + render_report(report)
        + '<details><summary>审查范围与覆盖说明</summary>' + render_report("\n".join(notes))
        + '</details></body></html>', encoding="utf-8")
    return destination
