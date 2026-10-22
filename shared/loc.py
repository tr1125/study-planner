"""Logical lines of code per harness responsibility (API file vs SDK '# replaces:' lines).

A logical line is a non-blank line that is not a comment and not part of a
docstring.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

PARTS = ["loop", "tools", "history", "memory", "context", "compaction", "caching", "tokens"]
_REPLACES = re.compile(r"#\s*replaces:\s*([a-z ,]+)")


def _docstring_lines(source: str) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    return lines


def code_lines(path: Path) -> list[tuple[int, str]]:
    source = Path(path).read_text(encoding="utf-8")
    skip = _docstring_lines(source)
    out = []
    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or i in skip:
            continue
        out.append((i, line))
    return out


def api_loc(api_dir: Path) -> dict:
    api_dir = Path(api_dir)
    parts = {p: len(code_lines(api_dir / "harness" / f"{p}.py")) for p in PARTS}
    files = {f.name: len(code_lines(f)) for f in sorted(api_dir.glob("*.py")) if f.name != "__init__.py"}
    return {"parts": parts, "other_files": files, "total": sum(parts.values()) + sum(files.values())}


def sdk_loc(sdk_dir: Path) -> dict:
    sdk_dir = Path(sdk_dir)
    parts = {p: 0 for p in PARTS}
    files = {}
    for f in sorted(sdk_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        lines = code_lines(f)
        files[f.name] = len(lines)
        for _, line in lines:
            m = _REPLACES.search(line)
            if m:
                for name in (n.strip() for n in m.group(1).split(",")):
                    if name in parts:
                        parts[name] += 1
    return {"parts": parts, "files": files, "total": sum(files.values())}
