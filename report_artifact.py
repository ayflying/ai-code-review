"""生成可离线阅读的报告产物；模型内容仅作转义文本，不执行 HTML。"""

from html import escape
from pathlib import Path


def write_report(directory: Path, report: str, notes: list[str]) -> Path:
    destination = directory / "ai-code-review-report"
    destination.mkdir(parents=True, exist_ok=True)
    markdown = report + "\n\n## 审查范围与覆盖说明\n\n" + "\n".join(notes)
    (destination / "report.md").write_text(markdown + "\n", encoding="utf-8")
    (destination / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        '<title>代码审查详细报告</title><style>body{max-width:1000px;margin:32px auto;padding:0 20px;'
        'font:16px/1.8 system-ui;color:#202938}pre{white-space:pre-wrap;overflow-wrap:anywhere;'
        'font:inherit}h1{font-size:26px}details{margin-top:32px;border-top:1px solid #ddd}</style>'
        '<h1>代码审查详细报告</h1><pre>' + escape(report) + '</pre>'
        '<details><summary>审查范围与覆盖说明</summary><pre>' + escape("\n".join(notes))
        + '</pre></details></html>', encoding="utf-8")
    return destination
