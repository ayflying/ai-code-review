"""Demand-driven Git tree discovery; no checkout, links, or repository code.

Listings use bounded pipes, not unbounded capture or temporary output files.
A failed recursive partition is retried one directory at a time. Shared byte,
command, candidate and wall-clock limits also bound adversarial flat trees.
"""

import re
import subprocess
import threading
import time
from collections.abc import Callable

from changes import GitOutputLimitError, GitReadError

MAX_SCAN_BYTES = 16_000_000
MAX_SCAN_COMMANDS = 256
MAX_SCAN_SECONDS = 60
MAX_CANDIDATES = 10_000
MAX_RECORD_BYTES = 65_536
EXACT_GROUP_SIZE = 16


def failure_reason(error: Exception, limit: int) -> str:
    """Never expose command stderr, raw exception text or unsafe names."""
    if isinstance(error, GitOutputLimitError):
        return f"文件清单超过 {limit:,} 字节读取上限"
    if isinstance(error, subprocess.TimeoutExpired):
        return "Git 读取超时"
    if isinstance(error, GitReadError):
        return "Git 命令执行失败"
    if isinstance(error, OSError):
        return "无法启动 Git 或访问本机读取资源"
    return "Git 返回的数据无效"


class ScanBudgetError(ValueError):
    """The shared discovery budget, rather than a single partition, is spent."""


class TreeReader:
    def __init__(self, limit: int, safe_path: Callable[[str], bool], notes: list[str]):
        self.limit = limit
        self.safe_path = safe_path
        self.notes = notes
        self.deadline = time.monotonic() + MAX_SCAN_SECONDS
        self.remaining = MAX_SCAN_BYTES
        self.commands = MAX_SCAN_COMMANDS
        self.tree: dict[str, tuple[str, str, str]] = {}

    def note(self, text: str) -> None:
        # Malformed entries must not grow the coverage log without bound.
        if text not in self.notes:
            self.notes.append(text)

    def listing(self, args: list[str], limit: int, consume: Callable[[bytes], None]) -> None:
        seconds = min(45, self.deadline - time.monotonic())
        if seconds <= 0:
            raise ScanBudgetError("总扫描时间预算")
        if self.commands <= 0:
            raise ScanBudgetError("Git 命令次数预算")
        if self.remaining <= 0:
            raise ScanBudgetError("总扫描字节预算")
        self.commands -= 1
        process = subprocess.Popen(
            ["git", "--no-pager", "--literal-pathspecs", "ls-tree", "-z", *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            try:
                process.kill()
            except OSError:
                pass  # The child may have exited concurrently with the timer.

        timer = threading.Timer(seconds, expire)
        timer.daemon = True
        timer.start()
        pending = b""
        received = 0
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                received += len(chunk)
                self.remaining -= len(chunk)
                if self.remaining < 0:
                    raise ScanBudgetError("总扫描字节预算")
                if received > limit:
                    raise GitOutputLimitError()
                records = (pending + chunk).split(b"\0")
                pending = records.pop()
                for record in records:
                    if len(record) > MAX_RECORD_BYTES:
                        self.note("覆盖不完整：跳过超过单条路径记录上限的 Git 清单项。")
                    else:
                        consume(record)
                if len(pending) > MAX_RECORD_BYTES:
                    raise ValueError("oversized tree record")
            process.wait()
            if expired.is_set():
                raise subprocess.TimeoutExpired("git ls-tree", seconds)
            if process.returncode:
                raise GitReadError()
            if pending:
                raise ValueError("unterminated tree record")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()

    def entry(self, record: bytes, prefix: str = "") -> tuple[str, str, str, str] | None:
        try:
            metadata, name = record.split(b"\t", 1)
            mode, kind, sha = metadata.decode("ascii").split()
            path = prefix + name.decode("utf-8", errors="strict")
        except (ValueError, UnicodeError):
            self.note("覆盖不完整：跳过无法解析或非 UTF-8 的 Git 清单路径。")
            return None
        if not self.safe_path(path):
            self.note("覆盖不完整：跳过敏感或含控制字符的规范候选路径。")
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            self.note("覆盖不完整：跳过对象标识无效的 Git 清单项。")
            return None
        if kind not in {"blob", "tree", "commit"} or mode not in {
            "100644", "100755", "120000", "040000", "160000"
        }:
            self.note("覆盖不完整：跳过元数据无效的 Git 清单项。")
            return None
        return path, mode, kind, sha

    def save(self, entry: tuple[str, str, str, str]) -> None:
        path, mode, kind, sha = entry
        if len(self.tree) >= MAX_CANDIDATES and path not in self.tree:
            raise ScanBudgetError("候选文件或目录数量预算")
        self.tree[path] = mode, kind, sha

    def exact(self, after: str, paths: list[str]) -> None:
        """Literal, nonrecursive queries; a failed group cannot erase other groups."""
        def group(items: list[str]) -> None:
            wanted = set(items)

            def consume(record: bytes) -> None:
                entry = self.entry(record)
                if entry and entry[0] in wanted:
                    self.save(entry)

            try:
                self.listing(["--full-tree", after, "--", *items], self.limit, consume)
            except GitOutputLimitError as error:
                if len(items) > 1:
                    middle = len(items) // 2
                    group(items[:middle])
                    group(items[middle:])
                else:
                    self.note(f"覆盖不完整：精确规范路径查询{failure_reason(error, self.limit)}。")
            except ScanBudgetError:
                raise
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                self.note(f"覆盖不完整：精确规范路径查询：{failure_reason(error, self.limit)}。")

        for start in range(0, len(paths), EXACT_GROUP_SIZE):
            group(paths[start:start + EXACT_GROUP_SIZE])

    def recursive(self, root: str, sha: str, skill: bool) -> None:
        def consume(record: bytes, prefix: str, directories: list[tuple[str, str]] | None) -> None:
            entry = self.entry(record, prefix)
            if not entry:
                return
            path, mode, kind, oid = entry
            if kind == "tree" and mode == "040000":
                if directories is not None:
                    if len(directories) >= MAX_CANDIDATES:
                        raise ScanBudgetError("候选文件或目录数量预算")
                    directories.append((path + "/", oid))
            else:
                candidate = (path.endswith("/SKILL.md") if skill
                             else path.lower().endswith(".md"))
                if candidate:
                    self.save(entry)

        # Iterative traversal avoids Python recursion failure on very deep trees.
        pending = [(root, sha, True)]
        while pending:
            prefix, oid, recursive = pending.pop()
            children: list[tuple[str, str]] = []
            try:
                args = ["-r", oid] if recursive else [oid]
                cap = self.limit if recursive else min(self.remaining, MAX_SCAN_BYTES)
                self.listing(args, cap, lambda record: consume(
                    record, prefix, None if recursive else children))
            except GitOutputLimitError as error:
                if recursive:
                    self.note("规范递归清单超过分段上限，已按目录拆分继续读取。")
                    pending.append((prefix, oid, False))
                else:
                    self.note(f"覆盖不完整：单目录规范清单{failure_reason(error, cap)}。")
            except ScanBudgetError:
                raise
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                self.note(f"覆盖不完整：规范目录清单读取：{failure_reason(error, self.limit)}。")
            if len(pending) + len(children) > MAX_CANDIDATES:
                raise ScanBudgetError("候选文件或目录数量预算")
            pending.extend((path, child, True) for path, child in reversed(children))


def discover(after: str, exact_paths: list[str], roots: tuple[str, ...], limit: int,
             safe_path: Callable[[str], bool], notes: list[str]) -> dict[str, tuple[str, str, str]]:
    reader = TreeReader(limit, safe_path, notes)
    try:
        reader.exact(after, list(dict.fromkeys([*exact_paths, *(root.rstrip("/") for root in roots)])))
        for root in roots:
            entry = reader.tree.pop(root.rstrip("/"), None)
            if entry is None:
                continue
            mode, kind, sha = entry
            if kind == "tree" and mode == "040000":
                reader.recursive(root, sha, root != "docs/")
            else:
                reader.note("覆盖不完整：规范扫描根不是普通目录（不跟随链接/子模块）。")
    except ScanBudgetError as error:
        # Only internally generated budget labels, never Git stderr.
        reader.note(f"覆盖不完整：规范清单扫描达到{error}，保留已获取文档。")
    return reader.tree
