"""Exercise real runner paths with a local fake CLI, never a model or GitHub."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from labkit import runner
from labkit.common import read_json, source_digest
from labkit.preflight import Check, sandbox_check
from labkit.report import display_status, render_report

SOURCE = Path(__file__).resolve().parents[1]
FAKE_CLI = """import json, sys, time
from pathlib import Path
mode=sys.argv[1]
if '--version' in sys.argv:
    if mode=='version_failure': raise SystemExit(2)
    print('fixture-cli 1.0'); raise SystemExit(0)
print(json.dumps({'type':'thread.started','thread_id':'fixture'}),flush=True)
if mode=='failed':
    print('fixture error',file=sys.stderr); raise SystemExit(7)
if mode=='changed':
    p=Path('src/parkfee/__init__.py'); p.write_text(p.read_text()+'\\n# fixture change\\n')
if mode=='malformed': print('not JSON',flush=True)
if mode=='invalid_usage':
    print(json.dumps({'type':'turn.completed','usage':None}),flush=True); raise SystemExit(0)
if mode!='missing_completion':
    print(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':40,'output_tokens':10}}),flush=True)
if mode=='timeout': time.sleep(10)
"""


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("assets", "task", "instructions"):
            shutil.copytree(SOURCE / name, self.root / name)
        (self.root / "labkit").mkdir()
        shutil.copyfile(
            SOURCE / "labkit/test_summary.py", self.root / "labkit/test_summary.py"
        )
        self.fake = self.root / "fake_cli.py"
        self.fake.write_text(FAKE_CLI)
        self.cfg = {
            **runner.DEFAULTS,
            "model": "fixture-model",
            "reasoning_effort": "high",
        }

    def execute(self, mode):
        cfg = {**self.cfg, "codex_command": [sys.executable, str(self.fake), mode]}
        if mode == "timeout":
            cfg["timeout_seconds"] = 1
        with (
            patch.object(
                runner, "execution_checks", return_value=[Check("fixture", True)]
            ),
            patch.object(runner, "find_rollout", return_value=None),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            folder = runner.execute(self.root, "baseline", cfg)
        return folder, read_json(folder / "summary.json")

    def test_failed_preflight_never_starts_a_model_or_creates_a_run(self):
        with (
            patch.object(
                runner,
                "execution_checks",
                return_value=[Check("sandbox", False, "bwrap failure")],
            ),
            patch.object(runner, "run_process") as process,
        ):
            with self.assertRaisesRegex(ValueError, "모델은 호출하지 않았습니다"):
                runner.execute(self.root, "baseline", self.cfg)
        process.assert_not_called()
        self.assertFalse((self.root / "runs").exists())

    def test_zero_exit_without_source_changes_is_not_submitted(self):
        folder, summary = self.execute("noop")
        self.assertEqual(summary["execution_status"], "no_changes")
        self.assertEqual(summary["usage"]["input_tokens"], 100)
        self.assertEqual(display_status(summary)["grade"], "채점 전")
        self.assertFalse((self.root / "submissions").exists())
        with self.assertRaisesRegex(ValueError, "정상 종료하고 소스를 변경"):
            runner.submit_github(self.root, folder, self.cfg, summary)

    def test_changed_source_and_completed_turn_produce_an_ungraded_artifact(self):
        folder, summary = self.execute("changed")
        self.assertEqual(summary["execution_status"], "completed")
        self.assertTrue(summary["source_changed"])
        self.assertTrue(summary["comparison_valid"])
        self.assertEqual(summary["conditions"]["reasoning_effort"], "high")
        self.assertEqual(summary["grade"]["status"], "pending")
        self.assertTrue((self.root / "submissions" / (folder.name + ".zip")).is_file())

    def test_direct_venv_invocation_passes_python_tools_without_shell_activation(self):
        # A bare PATH reproduces the real rehearsal's missing pytest/python issue.
        with (
            patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}),
            patch.object(runner, "run_process", wraps=runner.run_process) as process,
        ):
            self.execute("changed")
        env = process.call_args.kwargs.get("env") or process.call_args.args[-1]
        self.assertEqual(
            Path(shutil.which("python", path=env["PATH"])), Path(sys.executable)
        )

    def test_process_failure_keeps_logs_without_creating_a_submission(self):
        folder, summary = self.execute("failed")
        self.assertEqual(summary["execution_status"], "failed")
        self.assertEqual(summary["exit_code"], 7)
        self.assertIn("fixture error", (folder / "codex-stderr.txt").read_text())
        self.assertEqual(display_status(summary)["execution"], "실행 실패")
        self.assertFalse((self.root / "submissions").exists())

    def test_timeout_preserves_recorded_usage_without_claiming_success(self):
        _, summary = self.execute("timeout")
        self.assertEqual(summary["execution_status"], "timeout")
        self.assertEqual(summary["usage"]["input_tokens"], 100)
        self.assertFalse((self.root / "submissions").exists())

    def test_missing_or_malformed_completion_is_not_success(self):
        for mode in ("malformed", "missing_completion", "invalid_usage"):
            with self.subTest(mode=mode):
                _, summary = self.execute(mode)
                self.assertEqual(summary["execution_status"], "failed")

    def test_version_failure_is_visible_without_completion(self):
        _, summary = self.execute("version_failure")
        self.assertEqual(summary["execution_status"], "error")
        self.assertNotIn("condition_id", summary)
        self.assertIn("error", summary)

    def test_source_inspection_failure_keeps_logs_and_usage(self):
        def inspect(workspace):
            if (
                "# fixture change"
                in (workspace / "src/parkfee/__init__.py").read_text()
            ):
                raise ValueError("fixture unreadable source")
            return source_digest(workspace)

        with patch.object(runner, "source_digest", side_effect=inspect):
            folder, summary = self.execute("changed")
        self.assertEqual(summary["execution_status"], "error")
        self.assertEqual(summary["usage"]["input_tokens"], 100)
        self.assertIn("fixture unreadable source", summary["error"])
        self.assertTrue((folder / "events.jsonl").exists())
        self.assertFalse((self.root / "submissions").exists())

    def test_fixed_documents_and_test_helper_are_protected(self):
        folder, summary = self.execute("changed")
        for name in ("docs/architecture/overview.md", "tools/test_summary.py"):
            with self.subTest(name=name):
                target = folder / "workspace" / name
                original = target.read_bytes()
                target.write_text("fixture change")
                summary["comparison_valid"] = True
                runner.make_submission(self.root, folder, summary)
                self.assertFalse(summary["comparison_valid"])
                target.write_bytes(original)

    def test_push_failure_is_saved_and_rendered(self):
        folder, summary = self.execute("changed")
        with (
            patch(
                "labkit.github_flow.push_submission",
                side_effect=ValueError("fixture denied"),
            ) as push,
        ):
            with self.assertRaisesRegex(ValueError, "fixture denied"):
                runner.submit_github(self.root, folder, self.cfg, summary)
        push.assert_called_once()
        saved = read_json(folder / "summary.json")
        self.assertEqual(saved["submission_status"], "failed")
        self.assertEqual(display_status(saved)["submission"], "제출 실패")
        self.assertIn("fixture denied", (self.root / "results.html").read_text())

    def test_doctor_is_short_and_keeps_diagnostics_without_starting_a_run(self):
        output = io.StringIO()
        with (
            patch.object(
                runner,
                "execution_checks",
                return_value=[
                    Check(
                        "샌드박스",
                        False,
                        "long diagnostic\nsecond line",
                        "PC 설정을 확인하세요.",
                    )
                ],
            ),
            patch(
                "labkit.github_flow.check_submission_ready",
                return_value="students/probe",
            ) as submission,
            patch("labkit.github_flow.check_results_ready"),
            patch.object(runner, "run_process") as process,
            contextlib.redirect_stdout(output),
        ):
            self.assertFalse(runner.doctor(self.root, cfg=self.cfg))
        self.assertIn("[FAIL] 샌드박스", output.getvalue())
        self.assertNotIn("long diagnostic", output.getvalue())
        self.assertIn("long diagnostic", (self.root / "doctor.log").read_text())
        self.assertFalse(submission.call_args.kwargs["require_enrollment"])
        process.assert_not_called()
        self.assertFalse((self.root / "runs").exists())

    def test_report_escapes_diagnostics_and_links_only_existing_logs(self):
        folder, summary = self.execute("failed")
        summary["error"] = "</script><script>alert(1)</script>"
        (folder / "summary.json").write_text(json.dumps(summary))
        html = render_report(self.root).read_text()
        self.assertNotIn(summary["error"], html)
        self.assertIn("codex-stderr.txt", html)
        self.assertIn("실행 실패", html)
        self.assertIn("채점 전", html)

    def test_sandbox_probe_failure_is_not_reported_as_ready(self):
        responses = [
            Check("help", True, "--permission-profile"),
            Check("git", True),
            Check("probe", False, "bwrap failure"),
        ]
        with patch("labkit.preflight.command_check", side_effect=responses) as call:
            result = sandbox_check(self.root, {**self.cfg, "codex_command": ["codex"]})
        self.assertFalse(result.ok)
        self.assertIn("bwrap failure", result.detail)
        command = call.call_args.args[1]
        self.assertIn("sandbox", command)
        self.assertNotIn("exec", command)
        self.assertFalse(list(self.root.glob(".lab-preflight-*")))

    def test_unrecognized_sandbox_cli_fails_closed(self):
        with patch(
            "labkit.preflight.command_check",
            side_effect=[Check("help", True, "unrecognized"), Check("git", True)],
        ):
            result = sandbox_check(self.root, {**self.cfg, "codex_command": ["codex"]})
        self.assertFalse(result.ok)
        self.assertIn("지원하지 않습니다", result.detail)


if __name__ == "__main__":
    unittest.main()
