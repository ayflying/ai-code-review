"""报告型入口：缺 OpenAI 密钥不读取 diff，不发起任何 AI 请求。"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# -I 隔离 PYTHONPATH 和当前工作目录，仅加载本目录的审查模块。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from changes import collect  # noqa: E402
from notify import notify_risk  # noqa: E402
from providers import review_with_fallback  # noqa: E402


def sanitize(text: str) -> str:
    for name in ("AI_REVIEW_OPENAI_API_KEY", "AI_REVIEW_CLAUDE_API_KEY", "AI_REVIEW_DINGTALK_WEBHOOK"):
        value = os.getenv(name, "").strip()
        if value:
            text = text.replace(value, "[已隐藏密钥]")
    # 模型输出可能包含终端转义或 Actions 命令；禁止把它当控制指令。
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return "\n".join("报告 | " + line for line in text.splitlines())


def main() -> int:
    if not os.getenv("AI_REVIEW_OPENAI_API_KEY", "").strip():
        print("未配置 OpenAI 密钥，跳过 AI Code Review（不会调用 Claude）。")
        return 0
    has_risk = False
    try:
        diff, notes = collect()
        if diff:
            report, attempts, has_risk = review_with_fallback(diff)
            notes.extend(attempts)
        else:
            report = "没有可供审查的文本变更，未调用 AI；不代表整个提交无风险。"
        body = "# AI Code Review\n\n" + "\n".join(notes) + "\n\n" + report
    except (ValueError, OSError, subprocess.SubprocessError):
        body = "# AI Code Review\n\n审查未完成：配置、Git 对象或运行环境异常。不能据此判断无风险。"
    safe = sanitize(body)
    # 日志为所有 Gitea 版本的主要报告入口，不依赖 GitHub 专属制品协议。
    print(safe)
    print(notify_risk(safe, has_risk))
    directory = Path(os.getenv("RUNNER_TEMP") or tempfile.gettempdir())
    try:
        (directory / "ai-code-review-report.md").write_text(safe + "\n", encoding="utf-8")
    except OSError:
        print("报告文件写入失败，请以上方日志为准。")
    # 独立输出供工作流最后的策略步骤判断，AI/通知失败仍不标记风险。
    output = os.getenv("GITHUB_OUTPUT", "")
    if output:
        try:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"has_risk={'true' if has_risk else 'false'}\n")
        except OSError:
            print("风险状态输出失败，不执行风险阻断。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
