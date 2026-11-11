"""分区超限拆分与局部失败不丢根规范的离线契约。"""

import unittest
from unittest.mock import patch

from changes import GitOutputLimitError, GitReadError
from context_tree import TreeReader, discover


class TreeTests(unittest.TestCase):
    def test_recursive_limit_retries_directory_and_keeps_partial(self):
        oid = "a" * 40
        child = "b" * 40
        notes = []
        reader = TreeReader(100, lambda path: True, notes)

        def listing(args, limit, consume):
            if args == ["-r", oid]:
                raise GitOutputLimitError()
            if args == [oid]:
                consume(f"100644 blob {oid}\troot.md".encode())
                consume(f"040000 tree {child}\tmodule".encode())
            elif args == ["-r", child]:
                consume(f"100644 blob {child}\trules.md".encode())

        with patch.object(reader, "listing", side_effect=listing):
            reader.recursive("docs/", oid, False)
        self.assertEqual(set(reader.tree), {"docs/root.md", "docs/module/rules.md"})
        self.assertTrue(any("按目录拆分继续读取" in note for note in notes))
        self.assertFalse(any("覆盖不完整" in note for note in notes))

    def test_bad_docs_partition_keeps_successful_root(self):
        oid = "a" * 40
        notes = []

        def listing(self, args, limit, consume):
            if "--full-tree" in args:
                consume(f"100644 blob {oid}\tREADME.md".encode())
                consume(f"040000 tree {oid}\tdocs".encode())
            else:
                raise GitReadError("secret")

        with patch.object(TreeReader, "listing", listing):
            tree = discover(oid, ["README.md"], ("docs/",), 1000, lambda path: True, notes)
        self.assertIn("README.md", tree)
        self.assertTrue(any("Git 命令执行失败" in note for note in notes))
        self.assertFalse(any("secret" in note for note in notes))
