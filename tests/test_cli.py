from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import agent_replay.cli as cli
import agent_replay.sessions as sessions
from agent_replay.sessions import new_session, save_session


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.directory = Path(self.tempdir.name)
        self.previous_directory = Path.cwd()
        os.chdir(self.directory)
        self.run_root = self.directory / ".agent-replay" / "runs"
        self.root_patch = patch.object(sessions, "_ROOT", self.run_root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self._restore_directory)

    def _restore_directory(self) -> None:
        os.chdir(self.previous_directory)

    def _save_session(self, command: list[str], stdout: str, exit_code: int = 0) -> dict:
        started = datetime.now(timezone.utc)
        session = new_session(
            command=command,
            label="test run",
            started_at=started,
            ended_at=started + timedelta(seconds=1),
            stdout=stdout,
            stderr="",
            exit_code=exit_code,
        )
        save_session(session)
        return session

    def test_record_saves_redacted_output(self) -> None:
        def run(command: list[str], **kwargs: object) -> cli.subprocess.CompletedProcess[str]:
            if command[0] == "git":
                return cli.subprocess.CompletedProcess(command, 128, "", "")
            return cli.subprocess.CompletedProcess(command, 0, "token=private-value\n", "")

        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch.object(cli.subprocess, "run", side_effect=run),
            patch("sys.argv", ["agent-replay", "record", "--", "python", "-c", "print('token=private-value')"]),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            result = cli.main()

        saved_files = list(self.run_root.glob("*.json"))
        self.assertEqual(result, 0)
        self.assertEqual(len(saved_files), 1)
        saved_text = saved_files[0].read_text(encoding="utf-8")
        self.assertNotIn("private-value", saved_text)
        self.assertIn("token=[REDACTED]", saved_text)
        self.assertIn("Saved run", errors.getvalue())

    def test_show_inspects_redacted_command(self) -> None:
        session = self._save_session(["tool", "[REDACTED_API_KEY]"], "output")
        output = io.StringIO()

        with patch("sys.argv", ["agent-replay", "show", session["id"]]), contextlib.redirect_stdout(output):
            result = cli.main()

        self.assertEqual(result, 0)
        self.assertIn("Command:", output.getvalue())
        self.assertIn("[REDACTED_API_KEY]", output.getvalue())

    def test_list_includes_saved_runs(self) -> None:
        session = self._save_session(["tool"], "output")
        output = io.StringIO()

        with patch("sys.argv", ["agent-replay", "list"]), contextlib.redirect_stdout(output):
            result = cli.main()

        self.assertEqual(result, 0)
        self.assertIn(session["id"], output.getvalue())

    def test_replay_prints_saved_output(self) -> None:
        session = self._save_session(["tool"], "saved output")
        output = io.StringIO()

        with patch("sys.argv", ["agent-replay", "replay", session["id"]]), contextlib.redirect_stdout(output):
            result = cli.main()

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "saved output")

    def test_compare_will_not_run_a_command_with_a_masked_argument(self) -> None:
        session = self._save_session(["tool", "[REDACTED_API_KEY]"], "output")
        errors = io.StringIO()

        with (
            patch.object(cli.subprocess, "run") as run,
            patch("sys.argv", ["agent-replay", "compare", session["id"], "--yes"]),
            contextlib.redirect_stderr(errors),
        ):
            result = cli.main()

        self.assertEqual(result, 2)
        run.assert_not_called()
        self.assertIn("cannot be rerun safely", errors.getvalue())

    def test_compare_reports_changed_output(self) -> None:
        session = self._save_session(["tool"], "before")
        output = io.StringIO()
        completed = cli.subprocess.CompletedProcess(["tool"], 0, "after", "")

        with (
            patch.object(cli.subprocess, "run", return_value=completed),
            patch("sys.argv", ["agent-replay", "compare", session["id"], "--yes"]),
            contextlib.redirect_stdout(output),
        ):
            result = cli.main()

        self.assertEqual(result, 1)
        self.assertIn("stdout differs", output.getvalue())

    def test_record_returns_127_when_command_is_missing(self) -> None:
        errors = io.StringIO()

        with (
            patch.object(cli.subprocess, "run", side_effect=FileNotFoundError),
            patch("sys.argv", ["agent-replay", "record", "--", "missing-command"]),
            contextlib.redirect_stderr(errors),
        ):
            result = cli.main()

        self.assertEqual(result, 127)
        self.assertIn("Command not found", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
