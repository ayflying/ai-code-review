"""Path resolution and index routing stay static and repository-local."""

import unittest

from rule_references import references, skill_routes


class RuleReferenceTests(unittest.TestCase):
    def test_markdown_backticks_fragments_and_encoded_spaces(self):
        text = '[Rules](../rules.md#L2) `local.md` [Spaces](<folder/rule file.md>) [Encoded](rule%20file.md)'
        result = references("pkg/index.md", text)
        self.assertEqual(result[0], ("rules.md", "../rules.md"))
        self.assertEqual(result[1], ("pkg/local.md", "local.md"))
        self.assertEqual(result[2], ("pkg/folder/rule file.md", "folder/rule file.md"))
        self.assertEqual(result[3], ("pkg/rule file.md", "rule file.md"))

    def test_scripts_urls_absolute_and_wildcards_are_not_rule_links(self):
        paths = ("run.ps1", "https://example.invalid/a.md", "/private.md", "C:/private.md",
                 "refs/*.md", "a.md?token=secret", "refs\\a.md", "//host/a.md")
        self.assertEqual(references("AGENTS.md", " ".join(f"`{path}`" for path in paths)), [])

    def test_routes_match_camel_case_plurals_and_csharp_only_in_index(self):
        text = "- `binding`\n  - Scene: ViewModel lifecycle.\n- `coding`\n  - Scene: C# rules.\n- `api`\n  - Scene: HTTP.\n"
        routes, unmatched = skill_routes("pkg/skills/index.md", text, ["src/ViewModels/MailViewModel.cs"], (".agents/skills/",))
        self.assertEqual([route[0] for route in routes], ["pkg/skills/binding/SKILL.md", "pkg/skills/coding/SKILL.md"])
        self.assertIn(".agents/skills/binding/SKILL.md", routes[0])
        self.assertEqual(unmatched, 1)
        self.assertEqual(skill_routes("pkg/AGENTS.md", text, ["src/x.cs"], ()), ([], 0))

    def test_secondary_operational_notes_do_not_override_scene_routing(self):
        text = "- `binding`\n  - Scene: UIForm lifecycle.\n- `asset-tools`\n  - Scene: Photoshop artwork.\n  - Combination: UIForm binding and lifecycle.\n"
        routes, unmatched = skill_routes("skills/index.md", text, ["Assets/UIForms/Mail.prefab"], ())
        self.assertEqual(routes, [("skills/binding/SKILL.md",)])
        self.assertEqual(unmatched, 1)


if __name__ == "__main__":
    unittest.main()
