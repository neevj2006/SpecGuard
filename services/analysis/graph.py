"""Bounded relative-import relationships, not a runtime call graph."""

import posixpath

SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")


def resolve_imports(edges: list[dict], paths: set[str]) -> list[dict]:
    resolved = []
    for edge in edges:
        specifier = edge["to"]
        target = None
        if specifier.startswith("."):
            stem = posixpath.normpath(posixpath.join(posixpath.dirname(edge["from"]), specifier))
            if stem in paths:
                target = stem
            elif not stem.startswith("../") and not stem.startswith("/"):
                candidates = {stem + ext for ext in SUFFIXES}
                candidates.update(stem + "/index" + ext for ext in SUFFIXES)
                if stem.endswith((".js", ".jsx", ".mjs", ".cjs")):
                    candidates.update(posixpath.splitext(stem)[0] + ext for ext in SUFFIXES)
                matches = candidates & paths
                if len(matches) == 1:
                    target = matches.pop()
        resolved.append(
            {**edge, "target": target, "resolution": "relative_path" if target else "unresolved"}
        )
    return resolved


def neighbors(edges: list[dict], changed: set[str], limit: int = 30) -> set[str]:
    adjacent = set()
    for edge in edges:
        target = edge.get("target")
        if not target:
            continue
        if edge["from"] in changed:
            adjacent.add(target)
        if target in changed:
            adjacent.add(edge["from"])
    return set(sorted(adjacent - changed)[:limit])
