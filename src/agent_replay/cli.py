from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

from . import __version__
from .sessions import (
    compare_session,
    load_session,
    new_session,
    read_sessions,
    replay_session,
    save_session,
)


def _redaction_pattern(value: str) -> str:
    try:
        re.compile(value)
    except re.error as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-replay",
        description="Keep a local, replayable record of a command-line agent run.",
    )
    parser.add_argument("--version", action="version", version=f"agent-replay {__version__}")
    commands = parser.add_subparsers(dest="action", required=True)

    record = commands.add_parser("record", help="run a command and save its output")
    record.add_argument("--label", help="short name for this run")
    record.add_argument(
        "--redact-regex",
        action="append",
        default=[],
        type=_redaction_pattern,
        metavar="PATTERN",
        help="also mask matches of this regular expression; can be repeated",
    )
    record.add_argument("command", nargs=argparse.REMAINDER, help="command to run after --")

    commands.add_parser("list", help="list saved runs")
    show = commands.add_parser("show", help="show a run's metadata")
    show.add_argument("run_id")

    replay = commands.add_parser("replay", help="print the saved output again")
    replay.add_argument("run_id")

    compare = commands.add_parser("compare", help="rerun a command and compare its output")
    compare.add_argument("run_id")
    compare.add_argument(
        "--yes",
        action="store_true",
        help="run the saved command without an interactive confirmation",
    )
    return parser


def _run_record(command: list[str], label: str | None, redaction_patterns: list[str]) -> int:
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("Give a command after --, for example: agent-replay record -- python -c \"print('hi')\"", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    except FileNotFoundError:
        print(f"Command not found: {command[0]}", file=sys.stderr)
        return 127
    except OSError as exc:
        print(f"Could not start command: {exc}", file=sys.stderr)
        return 126
    ended = datetime.now(timezone.utc)

    session = new_session(
        command=command,
        label=label,
        started_at=started,
        ended_at=ended,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
        redaction_patterns=redaction_patterns,
    )
    path = save_session(session)
    replay_session(session)
    print(f"\nSaved run {session['id']} to {path}", file=sys.stderr)
    return result.returncode


def _list() -> int:
    sessions = read_sessions()
    if not sessions:
        print("No saved runs yet. Start one with: agent-replay record -- <command>")
        return 0
    print(f"{'RUN':<13} {'EXIT':>4} {'SECONDS':>8}  COMMAND")
    for item in sessions:
        print(
            f"{item['id']:<13} {item['exit_code']:>4} "
            f"{item['duration_seconds']:>8.2f}  {item['display_command']}"
        )
    return 0


def _show(run_id: str) -> int:
    session = load_session(run_id)
    if any("[REDACTED" in part for part in session["command"]):
        print(
            "The saved command contains a masked argument and cannot be rerun safely. "
            "Use an environment variable for that secret and record the command again.",
            file=sys.stderr,
        )
        return 2
    print(f"Run:       {session['id']}")
    print(f"Label:     {session.get('label') or '—'}")
    print(f"Started:   {session['started_at']}")
    print(f"Duration:  {session['duration_seconds']:.2f}s")
    print(f"Exit code: {session['exit_code']}")
    print(f"Command:   {session['display_command']}")
    print(f"Changed:   {', '.join(session.get('changed_files', [])) or 'none'}")
    print(f"Output:    {session['stdout_bytes']} bytes stdout, {session['stderr_bytes']} bytes stderr")
    return 0


def _confirm(command: str) -> bool:
    if not sys.stdin.isatty():
        print("This command will run the saved process again. Add --yes to confirm in a non-interactive shell.", file=sys.stderr)
        return False
    answer = input(f"Run this command again?\n  {command}\n[y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _compare(run_id: str, yes: bool) -> int:
    session = load_session(run_id)
    if not yes and not _confirm(session["display_command"]):
        print("Comparison cancelled.")
        return 1
    command = session["command"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    except (FileNotFoundError, OSError) as exc:
        print(f"Could not start saved command: {exc}", file=sys.stderr)
        return 126
    same, details = compare_session(session, result.stdout, result.stderr, result.returncode)
    print("MATCH: output and exit code are unchanged." if same else "DIFFERENT: this run changed.")
    for detail in details:
        print(f"  {detail}")
    return 0 if same else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.action == "record":
            return _run_record(args.command, args.label, args.redact_regex)
        if args.action == "list":
            return _list()
        if args.action == "show":
            return _show(args.run_id)
        if args.action == "replay":
            replay_session(load_session(args.run_id))
            return 0
        if args.action == "compare":
            return _compare(args.run_id, args.yes)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"agent-replay: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
