from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import start


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "requirements-lab.txt").write_text("pytest>=8,<9\n")
        self.python = start.environment_python(self.root)
        self.python.parent.mkdir(parents=True)
        self.python.touch()

    def test_repeated_launch_does_not_reinstall_unchanged_requirements(self):
        with (
            patch("start.subprocess.run") as install,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(start.bootstrap(self.root), self.python)
            start.bootstrap(self.root)
            self.assertEqual(install.call_count, 1)
            (self.root / "requirements-lab.txt").write_text("pytest==8.4.2\n")
            start.bootstrap(self.root)
            self.assertEqual(install.call_count, 2)

    def test_failed_install_can_be_retried(self):
        with (
            patch(
                "start.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["pip"]),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                start.bootstrap(self.root)
        self.assertFalse((self.root / ".venv/.lab-requirements.sha256").exists())

    def test_prepare_keeps_participant_and_existing_work(self):
        (self.root / "config.json").write_text(
            json.dumps({"participant": "p17", "model": "old"})
        )
        (self.root / "edit").mkdir()
        (self.root / "edit/AGENTS.md").write_text("learner work")
        args = self.args(prepare=True, model="course-model", reasoning_effort="high")
        with (
            patch("labkit.runner.doctor", return_value=True),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(start.launch(self.root, args), 0)
        cfg = json.loads((self.root / "config.json").read_text())
        self.assertEqual(cfg["participant"], "p17")
        self.assertEqual(cfg["model"], "course-model")
        self.assertEqual((self.root / "edit/AGENTS.md").read_text(), "learner work")

    def args(self, **changes):
        return argparse.Namespace(
            **{
                "action": None,
                "prepare": False,
                "model": None,
                "reasoning_effort": None,
                "check": False,
                "participant": None,
                **changes,
            }
        )

    def test_failed_doctor_stops_before_any_account_setup_or_enrollment(self):
        (self.root / "config.json").write_text(json.dumps({"model": "course-model"}))
        with (
            patch("labkit.runner.initialize"),
            patch("labkit.runner.doctor", return_value=False),
            patch("start.subprocess.run") as process,
            patch("start.answer") as prompt,
            patch("labkit.github_flow.enroll") as enroll,
        ):
            self.assertEqual(start.launch(self.root, self.args()), 1)
        process.assert_not_called()
        prompt.assert_not_called()
        enroll.assert_not_called()

    def test_noninteractive_missing_identity_does_not_hang(self):
        with patch("start.sys.stdin.isatty", return_value=False):
            with self.assertRaisesRegex(ValueError, "최초 설정"):
                start.answer("name: ")

    def test_prepared_learner_opens_menu_without_reentering_identity(self):
        (self.root / "config.json").write_text(
            json.dumps({"participant": "p17", "model": "course-model"})
        )
        with (
            patch("labkit.runner.initialize"),
            patch("labkit.runner.doctor", return_value=True) as doctor,
            patch("labkit.github_flow.enroll", return_value="students/p17") as enroll,
            patch("labkit.runner.run_menu") as menu,
            patch("start.subprocess.run") as process,
            patch("start.answer") as prompt,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(start.launch(self.root, self.args()), 0)
            self.assertEqual(start.launch(self.root, self.args()), 0)
        prompt.assert_not_called()
        process.assert_not_called()
        self.assertEqual(enroll.call_count, 2)
        self.assertEqual(enroll.call_args.args[2], "p17")
        self.assertEqual(menu.call_count, 2)
        self.assertEqual(doctor.call_count, 2)
        self.assertEqual(menu.call_args.kwargs["ready_config"]["participant"], "p17")

    def test_doctor_command_does_not_initialize_or_enroll(self):
        with (
            patch("start.ROOT", self.root),
            patch("labkit.runner.doctor", return_value=False) as doctor,
            patch("labkit.runner.initialize") as initialize,
            patch("labkit.github_flow.enroll") as enroll,
            patch("start.answer") as prompt,
        ):
            self.assertEqual(start.main(["--bootstrapped", "doctor"]), 1)
        doctor.assert_called_once()
        initialize.assert_not_called()
        enroll.assert_not_called()
        prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
