"""上传确认后，通过任务运行时协议定位HTML文件的产物ID；不外发运行时令牌。"""

import hashlib
import json
import os
import re
import urllib.request
from urllib.parse import urlsplit


def preview_url() -> str:
    server = os.environ["GITHUB_SERVER_URL"].rstrip("/")
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError("执行编号无效")
    name = f"ai-code-review-report-{attempt}"
    digest = hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()
    base = f"{server}/api/actions_pipeline/_apis/pipelines/workflows/{run_id}/artifacts"
    url = f"{base}/{digest}/download_url?itemPath={name}"
    token = os.environ["ACTIONS_RUNTIME_TOKEN"]
    # 不跟随重定向，防止运行时令牌随跳转泄露。
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        data = json.loads(response.read(100000))
    for item in data.get("value", []):
        if item.get("path") != f"{name}/report.html":
            continue
        location = item.get("contentLocation", "")
        parsed = urlsplit(location)
        match = re.fullmatch(rf"{re.escape(urlsplit(base).path)}/([0-9]+)/download", parsed.path)
        if parsed.netloc == urlsplit(server).netloc and parsed.scheme == "https" and match:
            return f"{server}/{repository}/actions/artifacts/{match[1]}/preview/report.html"
    raise ValueError("无法定位HTML报告预览，不发送无效链接")


if __name__ == "__main__":
    try:
        os.environ["AI_REVIEW_RUN_URL"] = preview_url()
        import subprocess
        import sys
        from pathlib import Path
        raise SystemExit(subprocess.call([sys.executable, "-I", str(Path(__file__).with_name("run.py")), "--notify"]))
    except (OSError, ValueError, KeyError):
        raise SystemExit("报告预览链接解析失败，未发送通知（不回显运行时数据）。")
