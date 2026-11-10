"""只读 Git 对象，不检出业务文件，不调用 textconv/外部 diff。"""

import os
import re
import subprocess
import tempfile
from pathlib import PurePosixPath

MAX_BYTES = 100_000
MAX_FILES = 60


def git(*args: str, limit: int = 200_000) -> bytes:
    # 文件落盘避免先无界捕获大型 diff 到内存；git 不执行仓库提供的过滤器。
    with tempfile.TemporaryFile() as output:
        process = subprocess.run(
            ["git", "--no-pager", *args], stdout=output, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, timeout=45, check=False,
        )
        if process.returncode:
            raise ValueError("无法读取 Git 对象，审查未完成")
        output.seek(0)
        data = output.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Git 输出超过限制，审查未完成")
    return data


def sensitive(path: str) -> bool:
    parts = PurePosixPath(path.lower()).parts
    name = parts[-1] if parts else ""
    return (any(part in {".git", ".ssh", "secrets", "credentials", "node_modules", "vendor"}
                for part in parts)
            or name.startswith(".env") or name in {"id_rsa", "id_ed25519"}
            or name.endswith((".pem", ".key", ".p12", ".pfx", ".lock", ".min.js")))


def collect_changes() -> tuple[str, list[str], str, list[str]]:
    after = os.getenv("AI_REVIEW_AFTER", "").strip() or git("rev-parse", "HEAD").decode().strip()
    before = os.getenv("AI_REVIEW_BEFORE", "").strip()
    notes: list[str] = []
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", after):
        raise ValueError("提交标识无效")
    git("rev-parse", "--verify", after + "^{commit}")
    if not before or set(before) == {"0"}:
        parents = git("rev-list", "--parents", "-n", "1", after).decode().split()
        # 新分支无可靠 before，不伪称覆盖整个分支历史。
        before = parents[1] if len(parents) > 1 else git("hash-object", "-t", "tree", "--stdin").decode().strip()
        notes.append("新分支或手动运行：仅审查 HEAD 相对第一父提交的变更（根提交相对空树）。")
    elif not re.fullmatch(r"[0-9a-fA-F]{40,64}", before):
        raise ValueError("推送前提交标识无效")
    else:
        git("rev-parse", "--verify", before + "^{commit}")
    notes.append(f"审查范围：{before} → {after}")
    paths = git("diff", "--name-only", "--no-renames", "-z", before, after, "--").decode("utf-8").split("\0")
    paths = [path for path in paths if path]
    diffs: list[str] = []
    used = 0
    skipped = 0
    for index, path in enumerate(paths):
        if sensitive(path) or index >= MAX_FILES:
            skipped += 1
            continue
        data = git("--literal-pathspecs", "diff", "--no-ext-diff", "--no-textconv",
                   "--no-renames", "--unified=8", before, after, "--", path,
                   limit=2_000_000)
        if b"Binary files " in data or b"GIT binary patch" in data:
            skipped += 1
            continue
        if len(data) > 30_000 or used + len(data) > MAX_BYTES:
            skipped += 1
            continue
        diffs.append(data.decode("utf-8", errors="replace"))
        used += len(data)
    if skipped:
        notes.append(f"覆盖不完整：排除敏感路径、二进制、生成物或超限文件共 {skipped} 个；不能据此判断整个提交安全。")
    return "\n".join(diffs), notes, after, paths


def collect() -> tuple[str, list[str]]:
    """保留仅收集差异的调用入口；编排使用同一次解析的提交和路径。"""
    diff, notes, _, _ = collect_changes()
    return diff, notes
