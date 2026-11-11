"""钉钉通知包括明确问题、改进建议和待确认事项，不自动重试避免重复。"""

import os
from urllib.parse import parse_qs, urlsplit

from providers import ReviewError, request_json
from notification_summary import short_text, summarize


def notify_risk(report: str, should_notify: bool) -> str:
    if not should_notify:
        return "无有效审查事项、审查未完成或未达到通知门槛，不发送钉钉通知。"
    webhook = os.getenv("AI_REVIEW_DINGTALK_WEBHOOK", "").strip()
    if not webhook:
        return "有审查事项，但未配置钉钉机器人密钥，未发送通知。"
    # 只允许钉钉官方地址，避免配置错误导致报告发送到任意外部主机。
    try:
        url = urlsplit(webhook)
        if (url.scheme != "https" or url.netloc != "oapi.dingtalk.com"
                or url.path != "/robot/send" or url.fragment
                or not parse_qs(url.query).get("access_token", [""])[0]):
            return "钉钉机器人地址无效，未发送通知。"
        repository = os.getenv("AI_REVIEW_REPOSITORY", "未知仓库")
        sha = os.getenv("AI_REVIEW_AFTER", "未知提交")
        run_url = os.getenv("AI_REVIEW_RUN_URL", "")
        keyword = os.getenv("AI_REVIEW_DINGTALK_KEYWORD", "gitea").strip()
        if not keyword or len(keyword.encode("utf-8")) > 200 or any(ord(c) < 32 for c in keyword):
            return "钉钉关键词无效，未发送通知。"
        repository_label = short_text(repository, 100)
        title = f"{repository_label} · {keyword} 代码审查报告"
        subject = short_text(os.getenv("AI_REVIEW_COMMIT_SUBJECT", ""), 100)
        header = f"# {repository_label}\n\n**{keyword} 代码审查报告** · {short_text(sha, 8)}\n\n"
        if subject:
            header += f"本次提交：{subject}\n\n"
        footer = ""
        if run_url:
            parsed_run = urlsplit(run_url)
            if parsed_run.scheme == "https" and parsed_run.netloc and not parsed_run.username:
                footer += f"\n\n[查看问题详细报告]({run_url.replace(')', '%29')})"
        else:
            footer += "\n\n详情请查看本次 CI 的审查日志。"
        pages = []
        current = ""
        # 每条保留仓库、关键词和链接；逐段拆分，严重项不会因摘要条数限制丢失。
        budget = 16000 - len((header + footer).encode("utf-8")) - 100
        if budget < 1000:
            return "通知标题或报告链接过长，未发送通知。"
        for paragraph in summarize(report).split("\n\n"):
            if len((current + "\n\n" + paragraph).encode("utf-8")) > budget and current:
                pages.append(current)
                current = ""
            current += ("\n\n" if current else "") + paragraph
        if current:
            pages.append(current)
        accepted = 0
        for index, page in enumerate(pages, 1):
            text = header + (f"第 {index}/{len(pages)} 条\n\n" if len(pages) > 1 else "") + page + footer
            try:
                response = request_json(webhook, {}, {
                    "msgtype": "markdown", "markdown": {"title": title, "text": text},
                })
            except (ReviewError, ValueError, OSError):
                return f"钉钉分条投递中断：已确认 {accepted}/{len(pages)} 条；当前条状态未知，未自动重试。"
            if type(response.get("errcode")) is not int or response["errcode"] != 0:
                return f"钉钉拒绝通知，已确认 {accepted}/{len(pages)} 条；请检查关键词、安全配置或限流。"
            accepted += 1
        return "钉钉机器人已接受审查通知。"
    except (ReviewError, ValueError, OSError):
        return "钉钉通知失败或投递状态未知，不影响 CI；未自动重试。"
