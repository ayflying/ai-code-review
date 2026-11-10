"""钉钉通知包括明确问题、改进建议和待确认事项，不自动重试避免重复。"""

import os
from urllib.parse import parse_qs, urlsplit

from providers import ReviewError, request_json
from notification_summary import short_text, summarize


def notify_risk(report: str, should_notify: bool) -> str:
    if not should_notify:
        return "无明确问题、建议或待确认事项，或审查未完成，不发送钉钉通知。"
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
        title = f"{keyword} 代码审查报告"
        subject = short_text(os.getenv("AI_REVIEW_COMMIT_SUBJECT", ""), 100)
        text = f"## {title}\n\n{short_text(repository, 100)} · {short_text(sha, 8)}\n\n"
        if subject:
            text += f"本次提交：{subject}\n\n"
        text += summarize(report)
        if run_url:
            parsed_run = urlsplit(run_url)
            if parsed_run.scheme == "https" and parsed_run.netloc and not parsed_run.username:
                text += f"\n\n[查看问题详细报告]({run_url.replace(')', '%29')})"
        else:
            text += "\n\n详情请查看本次 CI 的审查日志。"
        response = request_json(webhook, {}, {
            "msgtype": "markdown", "markdown": {"title": title, "text": text},
        })
        if type(response.get("errcode")) is not int or response["errcode"] != 0:
            return "钉钉拒绝通知，请检查机器人关键字或安全配置（不回显响应）。"
        return "钉钉机器人已接受审查通知。"
    except (ReviewError, ValueError, OSError):
        return "钉钉通知失败或投递状态未知，不影响 CI；未自动重试。"
