"""Offline contracts against real disposable Git object databases."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import review_context
from changes import git
from review_context import collect_context


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous = Path.cwd()
        os.chdir(self.root)
        # Cleanups are LIFO: leave cwd before deleting the temporary directory.
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.chdir, self.previous)
        self.command("init", "-q")
        self.command("config", "user.email", "contract@example.invalid")
        self.command("config", "user.name", "Contract Test")
        self.command("config", "core.autocrlf", "false")

    def command(self, *args, data=None):
        return subprocess.run(["git", *args], input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True).stdout

    def put(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)

    def commit(self):
        self.command("add", "--all")
        self.command("commit", "-qm", "fixture")
        return self.command("rev-parse", "HEAD").decode().strip()

    def test_selected_commit_not_worktree_numbering_and_deterministic_priority(self):
        fixtures = {
            "README.md": "committed root\nsecond\n",
            "AGENTS.md": "root rules",
            "CONTRIBUTING.md": "contributing",
            "app/AGENTS.md": "app rules",
            "app/README.md": "app readme",
            "app/nested/AGENTS.md": "nested rules",
            "app/nested/main.py": "source should never be context",
            "unrelated/README.md": "unrelated readme",
            "docs/design.md": "global docs",
            ".agents/skills/a/SKILL.md": "skill a",
            ".claude/skills/b/SKILL.md": "skill b",
            ".skills/c/SKILL.md": "skill c",
            "skills/d/SKILL.md": "skill d",
            "skills/d/run.py": "raise SystemExit('never run')",
        }
        for path, text in fixtures.items():
            self.put(path, text)
        after = self.commit()
        self.put("README.md", "worktree replacement")
        self.put("app/nested/README.md", "untracked must not load")
        with patch.object(review_context, "git", wraps=git) as calls:
            text, notes, counts = collect_context(after, ["app/nested/main.py"])
        self.assertIn("1: committed root\n2: second", text)
        self.assertNotIn("worktree replacement", text)
        self.assertNotIn("untracked must not load", text)
        self.assertNotIn("source should never", text)
        self.assertNotIn("unrelated readme", text)
        self.assertNotIn("never run", text)
        self.assertEqual(counts["README.md"], 2)
        self.assertEqual(list(counts)[:5], ["AGENTS.md", "README.md", "CONTRIBUTING.md",
                                          "app/AGENTS.md", "app/README.md"])
        self.assertEqual(list(counts)[-1], "docs/design.md")
        self.assertTrue(all(path in counts for path in fixtures if path.endswith("/SKILL.md")))
        self.assertFalse(any("app/nested/README.md" in note and "缺失" in note for note in notes))
        # Every blob read uses an object ID, never after:path or filesystem paths.
        for call in calls.call_args_list:
            if call.args[0] == "cat-file":
                self.assertRegex(call.args[2], r"^[0-9a-f]{40,64}$")

    def test_unsafe_utf8_binary_and_oversize_are_skipped_whole(self):
        self.put("README.md", "valid\n")
        self.put("AGENTS.md", b"\xffinvalid")
        self.put("CONTRIBUTING.md", b"binary\x00content")
        self.put("docs/large.md", "X" * (review_context.MAX_FILE_BYTES + 1))
        self.put("docs/credentials/README.md", "secret sentinel")
        self.put("docs/secrets/AGENTS.md", "secret rules")
        after = self.commit()
        with patch.object(review_context, "git", wraps=git) as calls:
            text, notes, counts = collect_context(after, [])
        reads = [call.args for call in calls.call_args_list if call.args[0] == "cat-file"]
        large_sha = self.command("rev-parse", f"{after}:docs/large.md").decode().strip()
        self.assertIn(("cat-file", "-s", large_sha), reads)
        self.assertNotIn(("cat-file", "blob", large_sha), reads)
        for index, args in enumerate(reads):
            if args[1] == "blob":
                self.assertEqual(reads[index - 1], ("cat-file", "-s", args[2]))
        self.assertEqual(counts, {"README.md": 1})
        self.assertNotIn("secret", text)
        self.assertNotIn("X" * 20, text)
        self.assertTrue(any("UTF-8" in note for note in notes))
        self.assertTrue(any("二进制" in note for note in notes))
        self.assertTrue(any("整文件跳过" in note for note in notes))

    def test_symlink_blob_is_never_followed(self):
        self.put("AGENTS.md", "normal rules")
        after = self.commit()
        sha = self.command("hash-object", "-w", "--stdin", data=b"AGENTS.md").decode().strip()
        self.command("update-index", "--add", "--cacheinfo", f"120000,{sha},README.md")
        self.command("commit", "-qm", "symlink fixture")
        after = self.command("rev-parse", "HEAD").decode().strip()
        text, notes, counts = collect_context(after, [])
        self.assertNotIn("README.md", counts)
        self.assertNotIn("1: AGENTS.md", text)
        self.assertTrue(any("非普通 blob" in note for note in notes))

    def test_total_bytes_and_file_count_never_slice_a_document(self):
        for index in range(25):
            self.put(f"docs/{index:02d}.md", str(index) + "x" * 11_998)
        after = self.commit()
        text, notes, counts = collect_context(after, [])
        self.assertEqual(len(counts), 4)
        self.assertLessEqual(len(text.encode("utf-8")), 60_000)
        self.assertTrue(all(value == 1 for value in counts.values()))
        self.assertNotIn("DOCUMENT: docs/05.md", text)
        self.assertTrue(any("预算" in note or "总字节上限" in note for note in notes))
        self.assertTrue(any("20 文件上限" in note for note in notes))
        for index in range(25):
            self.put(f"docs/{index:02d}.md", "small")
        after = self.commit()
        _, notes, counts = collect_context(after, [])
        self.assertEqual(len(counts), 20)
        self.assertTrue(any("剩余文档未加载" in note for note in notes))

    def test_numbered_context_respects_per_batch_byte_budget(self):
        self.put("README.md", "规则\n" * 100)
        after = self.commit()
        text, notes, counts = collect_context(after, [], max_bytes=800)
        self.assertLessEqual(len(text.encode("utf-8")), 800)
        self.assertNotIn("README.md", counts)
        self.assertTrue(any("行号" in note for note in notes))

    def test_project_entry_package_rules_and_matched_skill_precede_external_skills(self):
        package = "Packages/project-rules"
        self.put("AGENTS.md", f"总规则：`{package}/AGENTS.md`；索引：`{package}/skills/index.md`。")
        rules = "总体规则\n" + "x" * 15000 + "\nUI binding must be serialized."
        self.put(f"{package}/AGENTS.md", rules + "\n索引 `skills/index.md`。")
        self.put(f"{package}/skills/index.md", """# Skill index
- `general-coding`
  - 场景：C# naming and exceptions.
- `view-binding`
  - 场景：ViewModel UIForm lifecycle.
- `server-api`
  - 场景：HTTP request response.
""")
        self.put(f"{package}/skills/general-coding/SKILL.md", "Use clear names.")
        self.put(f"{package}/skills/view-binding/SKILL.md", "细则 [binding](references/binding.md#rule)；工具 `scripts/run.py`。")
        self.put(f"{package}/skills/view-binding/references/binding.md", "Avoid runtime hierarchy lookup.")
        self.put(f"{package}/skills/view-binding/scripts/run.py", "raise SystemExit('MUST NOT RUN')")
        self.put(f"{package}/skills/server-api/SKILL.md", "unrelated server sentinel")
        for index in range(25):
            self.put(f".agents/skills/external-{index:02d}/SKILL.md", "external skill")
        after = self.commit()
        self.put(f"{package}/AGENTS.md", "uncommitted replacement")
        text, notes, counts = collect_context(after, ["src/Views/MailViewModel.cs"])
        important = ["AGENTS.md", f"{package}/AGENTS.md", f"{package}/skills/index.md",
                     f"{package}/skills/general-coding/SKILL.md", f"{package}/skills/view-binding/SKILL.md",
                     f"{package}/skills/view-binding/references/binding.md"]
        self.assertTrue(all(path in counts for path in important))
        self.assertLess(list(counts).index(important[-1]), next(
            index for index, path in enumerate(counts) if path.startswith(".agents/")))
        self.assertNotIn("uncommitted replacement", text)
        self.assertNotIn("unrelated server sentinel", text)
        self.assertNotIn("MUST NOT RUN", text)
        self.assertEqual(review_context.source_line(text, f"{package}/AGENTS.md", 3),
                         "UI binding must be serialized.")
        self.assertTrue(any("2 个 Skill 路由" in note and "1 个未匹配" in note for note in notes))

    def test_relative_links_root_fallback_cycles_and_explicit_missing(self):
        self.put("AGENTS.md", "规则 [entry](Packages/rules/AGENTS.md)。")
        self.put("Packages/rules/AGENTS.md", "`../../AGENTS.md`\n`../common.md`\n`guides/safety.md`\n`missing.md`")
        self.put("Packages/common.md", "relative rule")
        self.put("guides/safety.md", "root rule")
        after = self.commit()
        text, notes, counts = collect_context(after, ["src/main.py"])
        self.assertEqual(set(counts), {"AGENTS.md", "Packages/rules/AGENTS.md", "Packages/common.md", "guides/safety.md"})
        self.assertEqual(text.count("--- DOCUMENT: AGENTS.md ("), 1)
        self.assertTrue(any("Packages/rules/missing.md 未找到" in note for note in notes))
        self.assertFalse(any("src/AGENTS.md" in note for note in notes))

    def test_explicit_entry_precedes_large_readme_and_upgrades_ancestor_priority(self):
        self.put("AGENTS.md", "`pkg/AGENTS.md`")
        self.put("README.md", "supplement" * 3000)
        self.put("pkg/AGENTS.md", "`rules.md`\nprimary project rule")
        self.put("pkg/rules.md", "mandatory rule" * 700)
        after = self.commit()
        text, notes, counts = collect_context(after, ["pkg/src/main.py"], max_bytes=12000)
        self.assertEqual(list(counts)[:3], ["AGENTS.md", "pkg/AGENTS.md", "pkg/rules.md"])
        self.assertIn("mandatory rule", text)
        self.assertNotIn("README.md", counts)
        self.assertTrue(any("README.md" in note and "跳过" in note for note in notes))

    def test_references_keep_security_filters_and_never_read_code_or_external_paths(self):
        self.put("AGENTS.md", "\n".join(f"`{path}`" for path in (
            "../../outside.md", "https://example.invalid/rules.md", "C:/private.md",
            "secrets/rules.md", "run.py", "rules/link.md", "rules/credentials.md", "rules/invalid.md")))
        self.put("secrets/rules.md", "SECRET SENTINEL")
        self.put("run.py", "raise SystemExit('MUST NOT RUN')")
        self.put("rules/credentials.md", "api_key=PRIVATE SENTINEL")
        self.put("rules/invalid.md", b"\xffinvalid")
        self.commit()
        sha = self.command("hash-object", "-w", "--stdin", data=b"../../outside.md").decode().strip()
        self.command("update-index", "--add", "--cacheinfo", f"120000,{sha},rules/link.md")
        self.command("commit", "-qm", "link")
        after = self.command("rev-parse", "HEAD").decode().strip()
        text, notes, counts = collect_context(after, [])
        self.assertEqual(set(counts), {"AGENTS.md"})
        self.assertNotIn("PRIVATE SENTINEL", text)
        self.assertNotIn("SECRET SENTINEL", text)
        self.assertTrue(any("非普通 blob" in note for note in notes))
        self.assertTrue(any("疑似包含明文凭据" in note for note in notes))
        self.assertTrue(any("UTF-8" in note for note in notes))

    def test_reference_count_and_numbered_budget_are_bounded(self):
        self.put("AGENTS.md", "\n".join(f"`rules/{index}.md`" for index in range(8)))
        for index in range(8):
            self.put(f"rules/{index}.md", "rule" * 200)
        after = self.commit()
        with patch.object(review_context, "MAX_REFERENCES", 4):
            text, notes, counts = collect_context(after, [], max_bytes=2000)
        self.assertLessEqual(len(text.encode("utf-8")), 2000)
        self.assertTrue(any("规范引用达到 4 条上限" in note for note in notes))
        self.assertFalse(any(f"rules/{index}.md" in counts for index in range(4, 8)))
        self.assertTrue(any("整文件跳过" in note for note in notes))

    def test_plaintext_credentials_never_enter_context(self):
        self.put("AGENTS.md", "**密码**：fake-sensitive-value\npassword=another-fake")
        self.put("README.md", "正常说明")
        after = self.commit()
        text, notes, counts = collect_context(after, [])
        self.assertNotIn("AGENTS.md", counts)
        self.assertNotIn("fake-sensitive-value", text + "".join(notes))
        self.assertTrue(any("明文凭据" in note for note in notes))

    def test_invalid_revision_rejected_before_git(self):
        for after in ("HEAD", "-bad", "f" * 39, "f" * 65, "g" * 40, "f" * 40 + "\n"):
            with self.subTest(after=after), patch.object(review_context, "git") as command:
                with self.assertRaises(ValueError):
                    collect_context(after, [])
                command.assert_not_called()

    def test_large_business_tree_does_not_prevent_root_and_module_rules(self):
        self.put("README.md", "root rules")
        self.put("app/AGENTS.md", "module rules")
        self.put("app/main.py", "source")
        for index in range(40):
            self.put(f"Assets/unrelated-{index:03}.txt", "business asset")
        after = self.commit()
        with patch.object(review_context, "MAX_TREE_BYTES", 500):
            text, notes, counts = collect_context(after, ["app/main.py"])
        self.assertIn("README.md", counts)
        self.assertIn("app/AGENTS.md", counts)
        self.assertIn("module rules", text)
        self.assertFalse(any("未加载任何规范文档" in note for note in notes))

    def test_control_paths_and_gitlinks_never_loaded(self):
        self.put("README.md", "rules")
        after = self.commit()
        # update-index works even on hosts which cannot create control-name files.
        sha = self.command("hash-object", "-w", "--stdin", data=b"hidden rules").decode().strip()
        records = (f"100644 {sha}\tdocs/bad\nname.md\0"
                   f"160000 {after}\tskills/submodule/SKILL.md\0").encode()
        self.command("update-index", "-z", "--index-info", data=records)
        self.command("commit", "-qm", "unsafe entries")
        after = self.command("rev-parse", "HEAD").decode().strip()
        text, notes, counts = collect_context(after, ["secrets/source.py", "app\nname/main.py"])
        self.assertEqual(counts, {"README.md": 1})
        self.assertNotIn("hidden rules", text)
        self.assertNotIn("bad\nname", "\n".join(notes))
        self.assertTrue(any("非普通 blob" in note for note in notes))

    def test_optional_ancestor_documents_missing_are_not_coverage_errors(self):
        self.put("README.md", "根目录规范")
        after = self.commit()
        text, notes, counts = collect_context(after, ["Assets/GameMain/Views/UI/main.cs"])
        self.assertIn("根目录规范", text)
        self.assertIn("README.md", counts)
        self.assertFalse(any("规范文档缺失" in note or "覆盖不完整" in note for note in notes))

    def test_no_project_documents_has_one_clear_scope_note(self):
        self.put("src/app.py", "pass")
        after = self.commit()
        _, notes, counts = collect_context(after, ["src/app.py"])
        self.assertFalse(counts)
        self.assertEqual(len([note for note in notes if "未加载任何项目规范" in note]), 1)
        self.assertNotIn("规范文档缺失", "\n".join(notes))

    def test_empty_document_and_unavailable_commit(self):
        self.put("README.md", "")
        after = self.commit()
        text, _, counts = collect_context(after, [])
        self.assertEqual(counts, {"README.md": 0})
        self.assertIn("0 lines", text)
        text, notes, counts = collect_context("0" * 40, [])
        self.assertEqual((text, counts), ("", {}))
        self.assertTrue(any("覆盖不完整" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
