"""独立危险度分数的统一校验与旧结果兼容，不改变severity门槛。"""

DEFAULT_SCORES = {"high": 90, "medium": 60, "low": 30}


def score_of(finding: dict) -> int:
    score = finding.get("score")
    if score is None:
        if "score" in finding:
            raise ValueError("危险度评分无效")
        return DEFAULT_SCORES[finding["severity"]]
    if type(score) is not int or not 0 <= score <= 100:
        raise ValueError("危险度评分必须为0到100的整数")
    reason = finding.get("score_reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.encode("utf-8")) > 1500:
        raise ValueError("危险度评分理由无效")
    return score


def score_reason(finding: dict) -> str:
    if "score" not in finding:
        return "模型未提供独立评分，暂用严重等级参考分；非独立危险度评估。"
    return finding["score_reason"]
