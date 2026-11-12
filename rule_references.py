"""Static Markdown rule links and skill-index routes; never execute a resolver."""

import posixpath
import re
from pathlib import PurePosixPath
from urllib.parse import unquote


def _targets(owner: str, target: str) -> tuple[str, ...]:
    target = unquote(target.split("#", 1)[0])
    if (not target.lower().endswith(".md") or target.startswith("/")
            or any(char in target for char in "\\:*?<>|\r\n\t")):
        return ()
    # Markdown paths are relative to their document; root paths are also common
    # in AGENTS.md. Existence is resolved against the reviewed Git tree only.
    return tuple(dict.fromkeys((posixpath.normpath(posixpath.join(
        str(PurePosixPath(owner).parent), target)), posixpath.normpath(target))))


def references(owner: str, text: str) -> list[tuple[str, ...]]:
    """Return alternative repository paths for each explicit local .md link."""
    targets = []
    pattern = r"`([^`\r\n]+)`|\[[^\]\r\n]*\]\(\s*(?:<([^>\r\n]+)>|([^\s)]+))(?:\s+\"[^\"\r\n]*\")?\s*\)"
    for match in re.finditer(pattern, text):
        candidates = _targets(owner, next(value for value in match.groups() if value is not None))
        if candidates and candidates not in targets:
            targets.append(candidates)
    return targets


def skill_routes(owner: str, text: str, paths: list[str], roots: tuple[str, ...]
                 ) -> tuple[list[tuple[str, ...]], int]:
    """Route index bullets by changed-path words, with conventional local paths.

    shortcut: lexical routing cannot infer business semantics; explicit .md
    links remain unconditional and unmatched routes are reported to reviewers.
    """
    if PurePosixPath(owner).name.lower() != "index.md":
        return [], 0
    terms: set[str] = set()
    for path in paths:
        stem = str(PurePosixPath(path).with_suffix(""))
        split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem)
        words = re.findall(r"[^\W_]+", stem.lower() + " " + split.lower())
        terms.update(word for word in words if len(word) >= 3)
        terms.update(word[:-1] for word in words if len(word) > 4 and word.endswith("s"))
        if path.lower().endswith(".cs"):
            terms.add("c#")
    blocks = re.findall(r"(?m)^- `([a-z][a-z0-9-]+)`[^\S\n]*\n((?:[ \t]+[^\n]*\n?)*)", text)
    ranked = []
    for name, description in blocks:
        scene = description.splitlines()[0] if description else ""
        score = sum(term in scene.lower() for term in terms)
        if score:
            local = posixpath.join(str(PurePosixPath(owner).parent), name, "SKILL.md")
            candidates = tuple(dict.fromkeys((local, *(root + name + "/SKILL.md" for root in roots))))
            ranked.append((score, candidates))
    ranked.sort(key=lambda item: -item[0])
    return [candidates for _, candidates in ranked], len(blocks) - len(ranked)
