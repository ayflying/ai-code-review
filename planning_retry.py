"""文件筛选专用超时重试，不重试认证、格式错误或详细审查请求。"""

import time

import providers

MAX_RETRIES = 5
TIMEOUT_MESSAGE = "接口请求超时（120秒）"


def request_with_retries(provider, prompt, notes):
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = providers.planning_request(provider, prompt)
            if attempt:
                notes.append(f"OPENAI 第 {attempt + 1} 次请求成功（已重试 {attempt} 次）")
            return result
        except providers.ReviewError as error:
            if provider != "OPENAI" or str(error) != TIMEOUT_MESSAGE:
                raise
            notes.append(f"OPENAI 第 {attempt + 1} 次请求超时（120秒）")
            if attempt == MAX_RETRIES:
                raise providers.ReviewError("OpenAI首次请求及5次重试均超时") from None
            # 有界退避，避免超时后立即对服务发起连续请求。
            time.sleep(min(2 ** attempt, 8))
