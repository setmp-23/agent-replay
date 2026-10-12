from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(".agent-replay") / "runs"
_ID_RE = re.compile(r"^[0-9a-f]{8}$")
_REDACTIONS = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (
        re.compile(r"(?i)(\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password)\s*[=:]\s*)[^\s&]+"),
        r"\1[REDACTED]",
    ),
]


def redact(value: str, extra_patterns: list[str] | None = None) -> str:
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    for expression in extra_patterns or []:
        value = re.sub(expression, "[REDACTED_CUSTOM]", value)
    return value


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False, timeout=2
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _changed_files() -> list[str]:
    status = _git_value("status", "--porcelain", "--untracked-files=all")
    if not status:
        return []
    names = []
    for line in status.splitlines():
        name = line[3:].strip()
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        if name:
            names.append(name)
    return names


def _display_command(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def new_session(
    *,
    command: list[str],
    label: str | None,
    started_at: datetime,
    ended_at: datetime,
    stdout: str,
    stderr: str,
    exit_code: int,
    redaction_patterns: list[str] | None = None,
) -> dict[str, Any]:
    patterns = redaction_patterns or []
    safe_command = [redact(part, patterns) for part in command]
    safe_stdout = redact(stdout, patterns)
    safe_stderr = redact(stderr, patterns)
    return {
        "schema_version": 1,
        "id": uuid.uuid4().hex[:8],
        "label": redact(label) if label else None,
        "redaction_patterns": patterns,
        "started_at": started_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0.0, (ended_at - started_at).total_seconds()),
        "command": safe_command,
        "display_command": _display_command(safe_command),
        "exit_code": exit_code,
        "stdout": safe_stdout,
        "stderr": safe_stderr,
        "stdout_bytes": len(stdout.encode("utf-8", errors="replace")),
        "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
        "git_commit": _git_value("rev-parse", "--short", "HEAD"),
        "changed_files": _changed_files(),
        "output_sha256": hashlib.sha256((safe_stdout + "\0" + safe_stderr).encode()).hexdigest(),
    }


def session_path(run_id: str) -> Path:
    if not _ID_RE.fullmatch(run_id):
        raise ValueError("Run IDs are eight lowercase hexadecimal characters. Use `agent-replay list` to find one.")
    return _ROOT / f"{run_id}.json"


def save_session(session: dict[str, Any]) -> Path:
    path = session_path(session["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(session, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_session(run_id: str) -> dict[str, Any]:
    path = session_path(run_id)
    if not path.is_file():
        raise ValueError(f"Run {run_id} was not found in {path.parent}.")
    session = json.loads(path.read_text(encoding="utf-8"))
    if session.get("schema_version") != 1 or session.get("id") != run_id:
        raise ValueError(f"Run file {path} has an unsupported or invalid format.")
    return session


def read_sessions() -> list[dict[str, Any]]:
    if not _ROOT.is_dir():
        return []
    sessions = []
    for path in _ROOT.glob("*.json"):
        try:
            session = load_session(path.stem)
        except (ValueError, OSError, json.JSONDecodeError):
            continue
        sessions.append(session)
    return sorted(sessions, key=lambda item: item["started_at"], reverse=True)


def replay_session(session: dict[str, Any]) -> None:
    if session["stdout"]:
        sys.stdout.write(session["stdout"])
        sys.stdout.flush()
    if session["stderr"]:
        sys.stderr.write(session["stderr"])
        sys.stderr.flush()


def compare_session(
    session: dict[str, Any], stdout: str, stderr: str, exit_code: int
) -> tuple[bool, list[str]]:
    patterns = session.get("redaction_patterns", [])
    safe_stdout = redact(stdout, patterns)
    safe_stderr = redact(stderr, patterns)
    differences = []
    if safe_stdout != session["stdout"]:
        differences.append("stdout differs")
    if safe_stderr != session["stderr"]:
        differences.append("stderr differs")
    if exit_code != session["exit_code"]:
        differences.append(f"exit code changed ({session['exit_code']} → {exit_code})")
    return not differences, differences
