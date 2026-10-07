"""Application-level file guard and audit log.

This is the first line of defense. OpenShell (Landlock + network policy) is the
second: even if this code or the LLM goes wrong, the kernel still refuses access.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# Path components the agent must never touch, wherever they appear.
DENIED_PARTS = {"restricted", "secrets", "secret", "private", "confidential", "credentials",
                "비공개", "기밀", ".ssh", ".aws", ".config", ".git"}
DENIED_SUFFIXES = {".env", ".pem", ".key"}
MAX_READ_BYTES = 256 * 1024


class GuardError(PermissionError):
    pass


class Audit:
    """Append-only event log written to output/audit.json. Never stores file contents or secrets."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def log(self, kind: str, **data) -> None:
        self.events.append({"t": round(time.time(), 3), "kind": kind, **data})

    def of(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["kind"] == kind]

    def to_json(self) -> str:
        return json.dumps(self.events, ensure_ascii=False, indent=2)


class PathGuard:
    def __init__(self, read_roots: list[Path], write_root: Path, audit: Audit) -> None:
        self.read_roots = [p.resolve() for p in read_roots]
        self.write_root = write_root.resolve()
        self.audit = audit

    @staticmethod
    def _denied(p: Path) -> str | None:
        for part in p.parts:
            if part.lower() in DENIED_PARTS:
                return f"denied path component '{part}'"
        if p.suffix.lower() in DENIED_SUFFIXES or p.name.lower().startswith(".env"):
            return f"denied file type '{p.name}'"
        return None

    @staticmethod
    def _within(p: Path, root: Path) -> bool:
        return p == root or root in p.parents

    def _denied_below(self, real: Path, root: Path) -> str | None:
        # Only judge the part below the allowed root, so e.g. macOS /private/tmp roots stay usable.
        return self._denied(real.relative_to(root)) if real != root else self._denied(Path(real.name))

    def check_read(self, path: Path) -> Path:
        # resolve() follows symlinks, so a link inside input/ pointing at secrets/ is caught here.
        real = Path(path).resolve()
        root = next((r for r in self.read_roots if self._within(real, r)), None)
        reason = "outside allowed read roots" if root is None else self._denied_below(real, root)
        if reason:
            self.audit.log("blocked_read", path=str(path), reason=reason)
            raise GuardError(f"read blocked: {path} ({reason})")
        return real

    def read_text(self, path: Path) -> str:
        real = self.check_read(path)
        data = real.read_bytes()[:MAX_READ_BYTES]
        self.audit.log("file_read", path=str(real), bytes=len(data))
        return data.decode("utf-8", errors="replace")

    def write_text(self, name: str, text: str) -> Path:
        target = (self.write_root / name).resolve()
        if not self._within(target, self.write_root) or self._denied_below(target, self.write_root):
            self.audit.log("blocked_write", path=str(target))
            raise GuardError(f"write blocked: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        self.audit.log("file_write", path=str(target), bytes=len(text.encode()))
        return target
