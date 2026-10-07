"""Collect input documents through the PathGuard and attach cheap deterministic signals."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .guard import GuardError, PathGuard

_DATE_PATTERNS = [
    re.compile(r"(20\d{2}|19\d{2})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(20\d{2}|19\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일"),
]
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")

# Phrases that suggest the document is trying to instruct the agent or move data out.
# These are signals for the LLM and the audit log, not the enforcement mechanism.
_INSTRUCTION_HINTS = [
    r"업로드", r"upload", r"전송하", r"보내(라|세요|줘)", r"send\s+(it|this|to)", r"POST\b",
    r"무시하(고|라)", r"ignore (all|previous|the above)", r"시스템\s*(설정|프롬프트)",
    r"system prompt", r"api[_ ]?key", r"token", r"비밀번호", r"password",
    r"https?://", r"[a-z0-9-]+\.(example|com|net|io|org|kr)\b",
]
_INSTRUCTION_RE = re.compile("|".join(_INSTRUCTION_HINTS), re.I)


@dataclass
class Doc:
    id: str
    path: str                     # relative to input dir
    text: str
    bytes: int
    dates: list[str] = field(default_factory=list)
    years: list[str] = field(default_factory=list)
    instruction_hints: list[str] = field(default_factory=list)

    def brief(self) -> dict:
        d = asdict(self)
        d.pop("text")
        return d


def _dates(s: str) -> list[str]:
    out = []
    for pat in _DATE_PATTERNS:
        for y, m, d in pat.findall(s):
            out.append(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
    return sorted(set(out))


def load_docs(input_dir: Path, guard: PathGuard) -> list[Doc]:
    docs: list[Doc] = []
    for p in sorted(input_dir.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        rel = str(p.relative_to(input_dir))
        try:
            text = guard.read_text(p)
        except GuardError:
            continue  # already recorded in the audit log
        if "\x00" in text:
            continue  # binary
        haystack = rel + "\n" + text
        hints = sorted({m.group(0) for m in _INSTRUCTION_RE.finditer(text)})
        docs.append(Doc(
            id=f"D{len(docs) + 1:02d}",
            path=rel,
            text=text,
            bytes=len(text.encode()),
            dates=_dates(haystack),
            years=sorted(set(_YEAR.findall(haystack))),
            instruction_hints=hints,
        ))
        if hints:
            guard.audit.log("instruction_hint", doc=rel, hints=hints)
    return docs
