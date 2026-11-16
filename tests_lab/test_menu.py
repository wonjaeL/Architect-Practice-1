"""Continuous practice and submission retries do not restart the model."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from labkit import runner
from labkit.common import write_json


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "runs/20261116-000000-abcd"
        write_json(
            self.folder / "summary.json",
            {
                "execution_status": "completed",
                "techniques": ["routing"],
                "note": "original",
            },
        )
        self.cfg = {**runner.DEFAULTS, "participant": "p17", "model": "fixture"}
        for target, kwargs in [
            ("labkit.runner.config", {"return_value": self.cfg}),
            ("labkit.github_flow.submission_branch", {"return_value": "students/p17"}),
            (
                "labkit.runner.render_report",
                {"return_value": self.root / "results.html"},
            ),
            ("labkit.runner.webbrowser.open", {}),
        ]:
            mock = patch(target, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)

    def test_multiple_experiments_use_one_preparation_and_do_not_wait_for_grading(self):
        with (
            patch("builtins.input", side_effect=["1", "2", "0"]),
            patch.object(runner, "execute", return_value=self.folder) as execute,
            patch.object(runner, "doctor") as doctor,
            patch.object(runner, "submit_github") as submit,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runner.run_menu(self.root, ready_config=self.cfg)
        doctor.assert_not_called()
        self.assertEqual(
            [call.args[1] for call in execute.call_args_list],
            ["baseline", "disclosure"],
        )
        self.assertTrue(
            all(call.kwargs["prechecked"] for call in execute.call_args_list)
        )
        self.assertEqual(submit.call_count, 2)
        self.assertTrue(
            all(
                len(call.args) == 4 and not call.kwargs
                for call in submit.call_args_list
            )
        )

    def test_failed_submission_can_be_retried_without_another_model_run(self):
        with (
            patch("builtins.input", side_effect=["1", "5", "", "", "0"]),
            patch.object(runner, "execute", return_value=self.folder) as execute,
            patch.object(
                runner, "submit_github", side_effect=[ValueError("disconnected"), None]
            ) as submit,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runner.run_menu(self.root, ready_config=self.cfg)
        execute.assert_called_once()
        self.assertEqual(submit.call_count, 2)
        self.assertEqual(submit.call_args.args[3]["techniques"], ["routing"])
        self.assertEqual(submit.call_args.args[3]["note"], "original")

    def test_changed_configuration_is_checked_before_starting_another_run(self):
        with (
            patch("builtins.input", side_effect=["3", "0"]),
            patch.object(runner, "doctor", return_value=False) as doctor,
            patch.object(runner, "execute") as execute,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runner.run_menu(self.root, ready_config={**self.cfg, "model": "previous"})
        doctor.assert_called_once()
        execute.assert_not_called()

    def test_failed_execution_rechecks_readiness_before_next_experiment(self):
        write_json(self.folder / "summary.json", {"execution_status": "no_changes"})
        with (
            patch("builtins.input", side_effect=["1", "2", "0"]),
            patch.object(runner, "execute", return_value=self.folder) as execute,
            patch.object(runner, "doctor", return_value=False) as doctor,
            patch.object(runner, "submit_github") as submit,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runner.run_menu(self.root, ready_config=self.cfg)
        execute.assert_called_once()
        doctor.assert_called_once()
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
