from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import agent_replay.sessions as sessions
from agent_replay.sessions import (
    compare_session,
    load_session,
    new_session,
    redact,
    save_session,
    session_path,
)


class RedactionTests(unittest.TestCase):
    def test_redacts_common_secrets_and_custom_patterns(self) -> None:
        value = "Bearer abc.def token=private internal-ABCD1234"

        result = redact(value, [r"internal-[A-Z0-9]{8}"])

        self.assertIn("Bearer [REDACTED]", result)
        self.assertIn("token=[REDACTED]", result)
        self.assertIn("[REDACTED_CUSTOM]", result)
        self.assertNotIn("private", result)

    def test_custom_redaction_is_applied_to_comparison_output(self) -> None:
        session = {
            "redaction_patterns": [r"build-[0-9]+"],
            "stdout": "id=[REDACTED_CUSTOM]",
            "stderr": "",
            "exit_code": 0,
        }

        same, differences = compare_session(session, "id=build-42", "", 0)

        self.assertTrue(same)
        self.assertEqual(differences, [])


class SessionStorageTests(unittest.TestCase):
    def test_round_trips_a_session_in_the_current_directory(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session = new_session(
            command=["tool", "token=private"],
            label="sample",
            started_at=started,
            ended_at=started + timedelta(seconds=2),
            stdout="Bearer abc.def",
            stderr="",
            exit_code=0,
        )

        with tempfile.TemporaryDirectory() as directory, patch.object(
            sessions, "_ROOT", Path(directory) / ".agent-replay" / "runs"
        ):
            save_session(session)
            loaded = load_session(session["id"])

        self.assertEqual(loaded["id"], session["id"])
        self.assertEqual(loaded["command"][1], "token=[REDACTED]")
        self.assertEqual(loaded["stdout"], "Bearer [REDACTED]")

    def test_rejects_invalid_run_ids(self) -> None:
        with self.assertRaises(ValueError):
            session_path("../../secret")


if __name__ == "__main__":
    unittest.main()
