"""Offline contracts for bounded Git review batches."""
import os
import re
import unittest
from unittest.mock import patch

import changes


def patch_text(path="app.py", body="+hello\n", old=0, new=1, old_start=0, new_start=1):
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -{old_start},{old} +{new_start},{new} @@\n{body}")


def source_lines(text):
    return [line for line in text.splitlines(keepends=True)
            if line[:1] in ("+", "-", " ") and not line.startswith(("+++", "---"))]


class SplitTests(unittest.TestCase):
    def test_utf8_budget_and_all_lines(self):
        text = patch_text(body="+中文😀\n" * 80, new=80)
        pieces, notes = changes.split_file_diff("app.py", text, 230)
        self.assertGreater(len(pieces), 1)
        self.assertFalse(notes)
        self.assertTrue(all(len(piece.encode()) <= 230 for piece in pieces))
        self.assertEqual(sum((source_lines(piece) for piece in pieces), []), source_lines(text))

    def test_large_mixed_hunk_correct_coordinates(self):
        body = " context\n" * 4 + "-old\n" * 35 + "+new\n" * 43 + " tail\n" * 3
        text = patch_text(body=body, old=42, new=50, old_start=10, new_start=20)
        pieces, notes = changes.split_file_diff("app.py", text, 150)
        self.assertFalse(notes)
        old_pos, new_pos = 10, 20
        for piece in pieces:
            match = re.search(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", piece)
            old_start, old_n, new_start, new_n = map(int, match.groups())
            lines = source_lines(piece)
            self.assertEqual(old_n, sum(line[0] in " -" for line in lines))
            self.assertEqual(new_n, sum(line[0] in " +" for line in lines))
            self.assertEqual(old_start, old_pos if old_n else old_pos - 1)
            self.assertEqual(new_start, new_pos if new_n else new_pos - 1)
            old_pos += old_n
            new_pos += new_n
        self.assertEqual((old_pos, new_pos), (52, 70))
        self.assertEqual(sum((source_lines(piece) for piece in pieces), []), source_lines(text))

    def test_zero_count_insertion_and_deletion(self):
        for prefix, old, new in (("+", 0, 60), ("-", 60, 0)):
            text = patch_text(body=(prefix + "line\n") * 60, old=old, new=new,
                              old_start=7, new_start=7)
            pieces, notes = changes.split_file_diff("app.py", text, 150)
            self.assertFalse(notes)
            for piece in pieces:
                match = re.search(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", piece)
                a, b, c, d = map(int, match.groups())
                self.assertEqual((a, b) if prefix == "+" else (c, d), (7, 0))

    def test_whole_hunks_keep_original_headers(self):
        head = "diff --git a/a b/a\n--- a/a\n+++ b/a\n"
        hunks = [f"@@ -{i},1 +{i},1 @@ function\n-old\n+new\n" for i in range(1, 8)]
        pieces, notes = changes.split_file_diff("a", head + "".join(hunks), 110)
        self.assertFalse(notes)
        self.assertEqual(pieces, [head + hunk for hunk in hunks])

    def test_metadata_only_rename_and_mode(self):
        for metadata in ("similarity index 100%\nrename from a\nrename to b\n",
                         "old mode 100644\nnew mode 100755\n"):
            text = "diff --git a/a b/b\n" + metadata
            self.assertEqual(changes.split_file_diff("b", text, 24000), ([text], []))
            pieces, notes = changes.split_file_diff("b", text, 10)
            self.assertFalse(pieces)
            self.assertIn("覆盖不完整", notes[0])

    def test_no_newline_marker_attached_and_long_line_skipped(self):
        marker = "\\ No newline at end of file\n"
        text = patch_text(body="-old\n" + marker + "+new\n" + marker, old=1, new=1)
        pieces, notes = changes.split_file_diff("app.py", text, 115)
        self.assertFalse(notes)
        self.assertEqual(len(pieces), 2)
        self.assertTrue(all(piece.endswith(marker) for piece in pieces))
        text = patch_text(body="+" + "中" * 500 + "\n+short\n", new=2)
        pieces, notes = changes.split_file_diff("app.py", text, 130)
        self.assertIn("极端长行", notes[0])
        self.assertEqual(source_lines("".join(pieces)), ["+short\n"])
        self.assertIn("+2,1", pieces[0])


class BatchTests(unittest.TestCase):
    def collect(self, files, **limits):
        def read_diff(before, after, path):
            result = files[path]
            if isinstance(result, Exception):
                raise result
            return result.encode() if isinstance(result, str) else result

        with patch.object(changes, "_resolve_changes", return_value=("a" * 40, "b" * 40, [], list(files))), \
                patch.object(changes, "_read_diff", side_effect=read_diff) as reader, \
                patch.object(changes, "limit_value", side_effect=lambda name, default=None: default if default is not None else 160000):
            patches = [patch.object(changes, name, value) for name, value in limits.items()]
            for item in patches:
                item.start()
            try:
                result = changes.collect_batches()
            finally:
                for item in reversed(patches):
                    item.stop()
        return result, reader

    def test_multiple_files_membership_and_packing(self):
        files = {f"file{i}.py": patch_text(f"file{i}.py") for i in range(4)}
        (batches, notes, after), _ = self.collect(files, MAX_BATCH_BYTES=230)
        self.assertTrue(any("分批配置" in note for note in notes))
        self.assertEqual(after, "b" * 40)
        self.assertEqual([p for _, paths in batches for p in paths], list(files))
        self.assertLess(len(batches), 4)
        self.assertTrue(all(len(diff.encode()) <= 230 for diff, _ in batches))

    def test_batch_cap_retains_collected_and_marks_coverage(self):
        files = {f"{i}.py": patch_text(f"{i}.py", body="+line\n" * 40, new=40) for i in range(25)}
        (batches, notes, _), _ = self.collect(files, MAX_BATCH_BYTES=330)
        self.assertEqual(len(batches), 20)
        self.assertTrue(all(len(diff.encode()) <= 330 for diff, _ in batches))
        self.assertIn("覆盖不完整", "".join(notes))

    def test_total_budget_file_count_and_read_failure(self):
        files = {"bad.py": ValueError("too large"), "ok.py": patch_text(), "last.py": patch_text()}
        (batches, notes, _), reader = self.collect(files, MAX_BATCH_FILES=2)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(batches[0][1], ["ok.py"])
        self.assertIn("读取失败", "".join(notes))
        self.assertIn("文件数/批次数/总差异限制", "".join(notes))
        (batches, notes, _), _ = self.collect({"a": patch_text(), "b": patch_text()}, MAX_TOTAL_BYTES=100)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][1], ["a"])
        self.assertIn("覆盖不完整", "".join(notes))

    def test_sensitive_and_binary_never_sent(self):
        files = {".env": "SECRET", "a.png": b"Binary files a/a and b/a differ\n", "app.py": patch_text()}
        (batches, notes, _), reader = self.collect(files)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(batches[0][1], ["app.py"])
        self.assertNotIn("SECRET", batches[0][0])
        self.assertIn("共 2 个文件", "".join(notes))

    def test_failure_after_success_preserves_other_files(self):
        files = {"first.py": patch_text(), "bad.py": OSError("read failed"),
                 "last.py": patch_text(), "invalid.py": b"+\xff\n"}
        (batches, notes, _), _ = self.collect(files)
        self.assertEqual(batches[0][1], ["first.py", "last.py"])
        self.assertIn("读取失败", "".join(notes))
        self.assertIn("不是有效 UTF-8", "".join(notes))

    def test_configured_limits_reach_collector_and_input_reserve(self):
        files = {str(i): patch_text(str(i), body="+" + "x" * 700 + "\n") for i in range(4)}
        with patch.dict(os.environ, {"AI_REVIEW_MAX_BATCHES": "2", "AI_REVIEW_MAX_FILES": "3",
                                    "AI_REVIEW_BATCH_BYTES": "2000", "AI_REVIEW_INPUT_BYTES": "11000"}), \
                patch.object(changes, "_resolve_changes", return_value=("a" * 40, "b" * 40, [], list(files))), \
                patch.object(changes, "_read_diff", side_effect=lambda before, after, path: files[path].encode()):
            batches, notes, _ = changes.collect_batches()
        self.assertEqual(len(batches), 2)
        self.assertTrue(all(len(diff.encode()) <= 1000 for diff, _ in batches))
        self.assertIn("2 批、3 文件，每批 1000 字节", notes[0])
        self.assertTrue(any("覆盖不完整" in note for note in notes))

    def test_real_range_resolution_and_file_read_limit(self):
        before, after = "a" * 40, "b" * 40
        with patch.dict(os.environ, {"AI_REVIEW_BEFORE": before, "AI_REVIEW_AFTER": after}), \
                patch.object(changes, "git", side_effect=[b"ok", b"ok", b"odd\nname.py\0", patch_text().encode()]) as git:
            batches, _, resolved = changes.collect_batches()
        self.assertEqual(resolved, after)
        self.assertEqual(batches[0][1], ["odd\nname.py"])
        self.assertEqual(git.call_args.kwargs["limit"], 2_000_000)
        self.assertIn("--literal-pathspecs", git.call_args.args)
        self.assertIn("--no-textconv", git.call_args.args)


if __name__ == "__main__":
    unittest.main()
