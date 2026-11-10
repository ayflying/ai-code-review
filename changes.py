"""只读 Git 对象，不检出业务文件，不调用 textconv/外部 diff。"""

import os
import re
import subprocess
import tempfile
from pathlib import PurePosixPath

from settings import limit_value

MAX_BYTES = 100_000
MAX_FILES = 60
MAX_BATCH_BYTES = 100_000
MAX_BATCHES = 20
MAX_BATCH_FILES = 300
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 20_000_000  # 全局资源硬上限；默认实际预算为20*100000字节

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@([^\n]*)(?:\n)?$")


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


def _resolve_changes() -> tuple[str, str, list[str], list[str]]:
    """Resolve the Git range and authoritative paths once for both APIs."""
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
    return before, after, notes, paths


def _read_diff(before: str, after: str, path: str) -> bytes:
    # 产品范围：不审查本工具的接入文件，避免把内部协议反复变成业务待确认项。
    # 精确匹配专用入口，不排除其他业务CI或任意包含AI_REVIEW字样的代码。
    if path in {".gitea/workflows/ai-code-review.yml", ".gitea/workflows/ai-code-review.yaml"}:
        return b""
    return git("--literal-pathspecs", "diff", "--no-ext-diff", "--no-textconv",
               "--no-renames", "--unified=8", before, after, "--", path,
               limit=MAX_FILE_BYTES)


def _binary(data: bytes) -> bool:
    return b"Binary files " in data or b"GIT binary patch" in data


def collect_changes() -> tuple[str, list[str], str, list[str]]:
    """Legacy single-diff API, retaining its original limits."""
    before, after, notes, paths = _resolve_changes()
    diffs: list[str] = []
    used = 0
    skipped = 0
    for index, path in enumerate(paths):
        if sensitive(path) or index >= MAX_FILES:
            skipped += 1
            continue
        data = _read_diff(before, after, path)
        if _binary(data):
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


def split_file_diff(path: str, text: str, budget: int) -> tuple[list[str], list[str]]:
    """Split a Git file patch without inventing paths or changing source lines.

    Each fragment repeats the complete file metadata. No-newline markers belong
    to their preceding source line and must never be separated from it.
    """
    if len(text.encode("utf-8")) <= budget:
        return ([text] if text else []), []
    lines = re.findall(r"[^\n]*\n|[^\n]+$", text)
    starts = [i for i, line in enumerate(lines) if _HUNK.match(line)]
    if not starts:
        return [], [f"覆盖不完整：{path} 的文件头超过批次字节限制，已跳过。"]
    header = "".join(lines[:starts[0]])
    result: list[str] = []
    notes: list[str] = []
    skipped = 0
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        hunk = "".join(lines[start:end])
        if len((header + hunk).encode("utf-8")) <= budget:
            result.append(header + hunk)
            continue
        match = _HUNK.match(lines[start])
        assert match is not None
        old, old_count, new, new_count, suffix = match.groups()
        # Zero-count starts describe the line *before* the insertion/deletion.
        old_pos = int(old) + (int(old_count or "1") == 0)
        new_pos = int(new) + (int(new_count or "1") == 0)
        units: list[str] = []
        for line in lines[start + 1:end]:
            if line.startswith("\\") and units:
                units[-1] += line
            else:
                units.append(line)
        pending: list[str] = []
        segment_old, segment_new = old_pos, new_pos
        old_used = new_used = 0

        def render(body: list[str], old_n: int, new_n: int) -> str:
            old_start = segment_old if old_n else segment_old - 1
            new_start = segment_new if new_n else segment_new - 1
            return (header + f"@@ -{old_start},{old_n} +{new_start},{new_n} @@{suffix}\n"
                    + "".join(body))

        for unit in units:
            old_n = int(unit.startswith((" ", "-")))
            new_n = int(unit.startswith((" ", "+")))
            candidate = render(pending + [unit], old_used + old_n, new_used + new_n)
            if len(candidate.encode("utf-8")) > budget and pending:
                result.append(render(pending, old_used, new_used))
                pending = []
                old_used = new_used = 0
                segment_old, segment_new = old_pos, new_pos
                candidate = render([unit], old_n, new_n)
            if len(candidate.encode("utf-8")) > budget:
                skipped += 1
                old_pos += old_n
                new_pos += new_n
                segment_old, segment_new = old_pos, new_pos
                continue
            pending.append(unit)
            old_used += old_n
            new_used += new_n
            old_pos += old_n
            new_pos += new_n
        if pending:
            result.append(render(pending, old_used, new_used))
    if skipped:
        notes.append(f"覆盖不完整：{path} 有 {skipped} 行连同文件头无法放入单批（极端长行或超长文件头），已明确跳过。")
    return result, notes


def collect_batches() -> tuple[list[tuple[str, list[str]]], list[str], str]:
    """Bounded review patches and their Git-derived file membership."""
    max_batches = limit_value("AI_REVIEW_MAX_BATCHES", MAX_BATCHES)
    max_files = limit_value("AI_REVIEW_MAX_FILES", MAX_BATCH_FILES)
    batch_bytes = limit_value("AI_REVIEW_BATCH_BYTES", MAX_BATCH_BYTES)
    # 差异不能占满输入，至少留4KB给提示/协议、6KB给规范；更大规范仍动态裁整文件。
    input_bytes = limit_value("AI_REVIEW_INPUT_BYTES")
    batch_bytes = min(batch_bytes, max(1000, input_bytes - 10_000))
    # 总差异预算随批次数和单批大小增长，避免旧480KB上限让调大批次数无效。
    total_bytes = min(MAX_TOTAL_BYTES, max_batches * batch_bytes)
    before, after, notes, paths = _resolve_changes()
    notes.append(f"分批配置：最多 {max_batches} 批、{max_files} 文件，每批 {batch_bytes} 字节，总差异 {total_bytes} 字节。")
    batches: list[tuple[str, list[str]]] = []
    current = ""
    members: list[str] = []
    total = 0
    excluded = failed = limited = 0
    for index, path in enumerate(paths):
        if index >= max_files:
            limited += 1
            continue
        if sensitive(path):
            excluded += 1
            continue
        try:
            data = _read_diff(before, after, path)
        except (ValueError, OSError, subprocess.SubprocessError):
            failed += 1
            notes.append(f"覆盖不完整：{path} 的 Git 差异读取失败或超过单文件 {MAX_FILE_BYTES} 字节限制，已跳过。")
            continue
        if _binary(data):
            excluded += 1
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            excluded += 1
            notes.append(f"覆盖不完整：{path} 的差异不是有效 UTF-8，已跳过而非替换源码字符。")
            continue
        pieces, split_notes = split_file_diff(path, text, batch_bytes)
        notes.extend(split_notes)
        for piece in pieces:
            # Git patches end in a newline; only add a separator if needed.
            separator = "\n" if current and not current.endswith("\n") else ""
            size = len((separator + piece).encode("utf-8"))
            if len(current.encode("utf-8")) + size > batch_bytes:
                batches.append((current, members))
                current, members = "", []
                separator = ""
                size = len(piece.encode("utf-8"))
            if len(batches) >= max_batches or total + size > total_bytes:
                limited += 1
                continue
            current += separator + piece
            total += size
            if path not in members:
                members.append(path)
    if current:
        batches.append((current, members))
    if excluded:
        notes.append(f"覆盖不完整：排除敏感路径、二进制或生成物共 {excluded} 个文件；不能据此判断整个提交安全。")
    if limited:
        notes.append(f"覆盖不完整：文件数/批次数/总差异限制（{max_files} 文件、{max_batches} 批、{total_bytes} 字节）导致 {limited} 个文件或片段跳过。")
    if failed:
        notes.append(f"覆盖不完整：{failed} 个文件读取失败；其他已收集差异保留。")
    return batches, notes, after


def collect() -> tuple[str, list[str]]:
    """保留仅收集差异的调用入口；编排使用同一次解析的提交和路径。"""
    diff, notes, _, _ = collect_changes()
    return diff, notes
