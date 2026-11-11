"""Collect bounded, untrusted documentation from Git objects, never the worktree.

Documents are evidence for review, not instructions to execute. No skill scripts,
symlinks, submodules, filters or other business-repository code are executed.
"""

import re
import subprocess
import unicodedata
from pathlib import PurePosixPath

from changes import git, sensitive
from context_tree import discover, failure_reason

MAX_FILES = 20
MAX_FILE_BYTES = 12_000
MAX_TOTAL_BYTES = 60_000
MAX_TREE_BYTES = 1_000_000
ROOT_DOCS = ("README.md", "AGENTS.md", "CONTRIBUTING.md")
SKILL_ROOTS = (".agents/skills/", ".claude/skills/", ".skills/", "skills/")


def _safe_path(path: str) -> bool:
    # Git paths use '/' on every platform. Reject ambiguous paths and log controls.
    return (bool(path) and not path.startswith("/") and "\\" not in path
            and all(part not in {"", ".", ".."} for part in path.split("/"))
            and not any(unicodedata.category(char).startswith("C") for char in path)
            and not sensitive(path))


def _candidates(paths: list[str], tree: dict[str, tuple[str, str, str]]) -> list[str]:
    candidates = list(ROOT_DOCS)
    directories: set[str] = set()
    for path in paths:
        if not _safe_path(path):
            continue
        parent = PurePosixPath(path).parent
        while str(parent) != ".":
            directories.add(str(parent))
            parent = parent.parent
    for directory in sorted(directories, key=lambda item: (item.count("/"), item)):
        candidates.extend((f"{directory}/AGENTS.md", f"{directory}/README.md"))
    names = sorted(tree)
    candidates.extend(path for path in names if path.endswith("/SKILL.md")
                      and any(path.startswith(root) for root in SKILL_ROOTS))
    # Root docs/ is deliberately global, but has lowest priority and the same caps.
    candidates.extend(path for path in names
                      if path.startswith("docs/") and path.lower().endswith(".md"))
    return list(dict.fromkeys(candidates))


def source_line(context: str, path: str, number: int) -> str:
    """按生成器的标题与连续行号取原文；文档正文始终带编号，不能伪造标题。"""
    active = False
    for line in context.splitlines():
        if line.startswith("--- DOCUMENT: "):
            active = bool(re.fullmatch(re.escape(f"--- DOCUMENT: {path} (") + r"[0-9]+ lines\) ---", line))
        elif active and line.startswith(f"{number}: "):
            return line.partition(": ")[2]
    return ""


def collect_context(after: str, paths: list[str], max_bytes: int = MAX_TOTAL_BYTES
                    ) -> tuple[str, list[str], dict[str, int]]:
    """Return numbered documents, coverage notes and loaded path -> line count.

    Limits apply to complete original UTF-8 blobs (not partially sliced rules).
    Git/output failures are advisory: retain review availability with an explicit
    incomplete-coverage note. Invalid revision syntax is rejected before Git runs.
    """
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", after):
        raise ValueError("提交标识无效")
    notes: list[str] = []
    try:
        git("rev-parse", "--verify", after + "^{commit}")
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        reason = failure_reason(error, MAX_TREE_BYTES)
        return "", [f"覆盖不完整：{reason}；未加载项目规范文档，代码差异审查继续。"], {}
    # Root/ancestor rules are queried literally in small groups, never by a full
    # repository walk. Only the documented global roots permit recursion.
    tree = discover(after, _candidates(paths, {}), (*SKILL_ROOTS, "docs/"),
                    MAX_TREE_BYTES, _safe_path, notes)

    documents: list[str] = []
    line_counts: dict[str, int] = {}
    used = 0
    rendered_used = 0
    max_bytes = min(max_bytes, MAX_TOTAL_BYTES)
    attempted = 0
    for path in _candidates(paths, tree):
        entry = tree.get(path)
        if entry is None:
            notes.append(f"规范文档缺失：{path}（覆盖不完整）。")
            continue
        mode, kind, sha = entry
        if mode not in {"100644", "100755"} or kind != "blob":
            notes.append(f"覆盖不完整：跳过非普通 blob 规范文档 {path}（不跟随链接/子模块）。")
            continue
        if attempted >= MAX_FILES:
            notes.append("覆盖不完整：规范候选超过 20 文件上限，剩余文档未加载。")
            break
        attempted += 1
        try:
            size = int(git("cat-file", "-s", sha, limit=100).strip())
            if size < 0 or size > MAX_FILE_BYTES or used + size > max_bytes:
                notes.append(f"覆盖不完整：规范文档 {path} 超过单文件或总字节上限，整文件跳过（未截取）。")
                continue
            data = git("cat-file", "blob", sha, limit=MAX_FILE_BYTES)
            if len(data) != size:
                raise ValueError("blob size mismatch")
            text = data.decode("utf-8", errors="strict")
            if any(unicodedata.category(char) == "Cc" and char not in "\t\r\n" for char in text):
                notes.append(f"覆盖不完整：规范文档 {path} 为二进制/含控制字符，已跳过。")
                continue
        except UnicodeError:
            notes.append(f"覆盖不完整：规范文档 {path} 不是严格 UTF-8，已跳过。")
            continue
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            notes.append(f"覆盖不完整：规范文档 {path} Git 对象读取失败："
                         f"{failure_reason(error, MAX_FILE_BYTES)}，已跳过。")
            continue
        # 文档可能包含部署凭据；宁可跳过整份，也不把已识别的秘密发到模型。
        if re.search(r"(?im)(?:password|passwd|api[_ -]?key|access[_ -]?token|密码)"
                     r"[\s*`\"']*[:=：][^\r\n]+|-----BEGIN [A-Z ]*PRIVATE KEY-----", text):
            notes.append(f"覆盖不完整：规范文档 {path} 疑似包含明文凭据，整文件跳过（不回显内容）。")
            continue
        lines = text.splitlines()
        document = (f"--- DOCUMENT: {path} ({len(lines)} lines) ---\n"
                    + "\n".join(f"{number}: {line}" for number, line in enumerate(lines, 1)))
        size_with_numbers = len(document.encode("utf-8")) + (2 if documents else 0)
        if rendered_used + size_with_numbers > max_bytes:
            notes.append(f"覆盖不完整：规范文档 {path} 加行号后超过本批上下文预算，整文件跳过。")
            continue
        line_counts[path] = len(lines)
        used += size
        rendered_used += size_with_numbers
        documents.append(document)
        notes.append(f"已加载规范文档：{path}（{len(lines)} 行）。")
    if not line_counts:
        notes.append("覆盖不完整：未加载任何规范文档，不能据此验证仓库规范。")
    return "\n\n".join(documents), list(dict.fromkeys(notes)), line_counts
