"""钉钉自定义机器人通知：只发已确认的风险结果，不自动重试避免重复。"""

import os
from urllib.parse import parse_qs, urlsplit

from providers import ReviewError, request_json


def notify_risk(report: str, has_risk: bool) -> str:
    if not has_risk:
        return "未发现明确风险或审查未完成，不发送钉钉通知。"
    webhook = os.getenv("AI_REVIEW_DINGTALK_WEBHOOK", "").strip()
    if not webhook:
        return "发现风险，但未配置钉钉机器人密钥，未发送通知。"
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
        text = f"## gitea 代码风险报告\n\n仓库：{repository}\n\n提交：{sha}\n\n"
        if run_url:
            text += f"完整报告：{run_url}\n\n"
        # 钉钉 Markdown 消息限制按 UTF-8 字节计算，预留 JSON/标题余量。
        remaining = max(0, 16000 - len(text.encode("utf-8")))
        raw = report.encode("utf-8")
        text += raw[:remaining].decode("utf-8", errors="ignore")
        if len(raw) > remaining:
            text += "\n\n报告过长已截断，请查看 CI 完整日志。"
        response = request_json(webhook, {}, {
            "msgtype": "markdown", "markdown": {"title": "gitea 代码风险报告", "text": text},
        })
        if type(response.get("errcode")) is not int or response["errcode"] != 0:
            return "钉钉拒绝通知，请检查机器人关键字或安全配置（不回显响应）。"
        return "钉钉机器人已接受风险通知。"
    except (ReviewError, ValueError, OSError):
        return "钉钉通知失败或投递状态未知，不影响 CI；未自动重试。"
