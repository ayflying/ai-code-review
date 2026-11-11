"""报告型入口：缺 OpenAI 密钥不读取 diff，不发起任何 AI 请求。"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# -I 隔离 PYTHONPATH 和当前工作目录，仅加载本目录的审查模块。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_review import review_batches  # noqa: E402
from changes import collect_batches  # noqa: E402
from notify import notify_risk  # noqa: E402
from report_artifact import write_report  # noqa: E402
from settings import limit_value, load_settings, policy  # noqa: E402


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
    should_notify = False
    notes = []
    report = "审查未完成，不能据此判断无风险。"
    try:
        load_settings()
        from review_plan import select_files
        shared_plan = ""

        def planner(commit: str, files: list[dict]):
            nonlocal shared_plan
            selected, shared_plan, plan_notes = select_files(
                commit, files, input_bytes=limit_value("AI_REVIEW_INPUT_BYTES"))
            return selected, plan_notes

        batches, notes, after = collect_batches(planner=planner)
        # 由已解析的Git提交获取说明，不信任事件中的可执行内容，也不依赖通知步骤的cwd。
        try:
            subject = subprocess.run(["git", "show", "-s", "--format=%s", after],
                                     check=True, capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
            os.environ["AI_REVIEW_COMMIT_SUBJECT"] = subject.strip()
        except (OSError, subprocess.SubprocessError):
            subject = ""
        if batches:
            report, attempts, has_risk, should_notify = review_batches(batches, after, shared_plan)
            notes.extend(attempts)
        else:
            report = "没有进入详细审查的文本变更（基础排除或规划筛选后为空），未执行代码详细审查；不代表整个提交无风险。"
        body = "# AI Code Review\n\n" + "\n".join(notes) + "\n\n" + report
    except (ValueError, OSError, subprocess.SubprocessError):
        body = "# AI Code Review\n\n审查未完成：配置、Git 对象或运行环境异常。不能据此判断无风险。"
    safe = sanitize(body)
    # 日志为所有 Gitea 版本的主要报告入口，不依赖 GitHub 专属制品协议。
    print(safe)
    if os.getenv("AI_REVIEW_DEFER_NOTIFY") != "true":
        print(notify_risk(safe, should_notify))
    directory = Path(os.getenv("RUNNER_TEMP") or tempfile.gettempdir())
    try:
        (directory / "ai-code-review-report.md").write_text(safe + "\n", encoding="utf-8")
        # 产物不含“报告 |”日志前缀，先展示问题，覆盖说明折叠在后。
        def clean(value: str) -> str:
            return "\n".join(line.removeprefix("报告 | ") for line in sanitize(value).splitlines())
        write_report(directory, clean(report), [clean(note) for note in notes])
        (directory / "ai-code-review-subject.txt").write_text(
            clean(os.getenv("AI_REVIEW_COMMIT_SUBJECT", "")), encoding="utf-8")
    except OSError:
        print("报告文件写入失败，请以上方日志为准。")
    # 独立输出供工作流最后的策略步骤判断，AI/通知失败仍不标记风险。
    output = os.getenv("GITHUB_OUTPUT", "")
    if output:
        try:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"has_risk={'true' if has_risk else 'false'}\n")
                stream.write(f"should_notify={'true' if should_notify else 'false'}\n")
        except OSError:
            print("风险状态输出失败，不执行风险阻断。")
    return 0


if __name__ == "__main__":
    # 固定入口协议 v1：不带参数生成报告；--policy 单独执行最终策略。
    if sys.argv[1:] == ["--policy"]:
        raise SystemExit(policy())
    if sys.argv[1:] == ["--notify"]:
        directory = Path(os.getenv("RUNNER_TEMP") or tempfile.gettempdir())
        try:
            report = (directory / "ai-code-review-report.md").read_text(encoding="utf-8")
            subject_path = directory / "ai-code-review-subject.txt"
            if subject_path.exists():
                os.environ["AI_REVIEW_COMMIT_SUBJECT"] = subject_path.read_text(encoding="utf-8")
            print(notify_risk(report, os.getenv("AI_REVIEW_SHOULD_NOTIFY") == "true"))
        except OSError:
            print("报告读取失败，未发送通知。")
        raise SystemExit(0)
    if sys.argv[1:]:
        raise SystemExit("不支持的审查入口参数")
    raise SystemExit(main())
