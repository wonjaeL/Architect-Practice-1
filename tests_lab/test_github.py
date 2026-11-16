"""로컬 bare 저장소로 검증한다. GitHub나 LLM을 호출하지 않는다."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from labkit.common import source_digest, write_json
from labkit.github_flow import (
    check_submission_ready,
    enroll,
    fetch_results,
    participant,
    push_submission,
    receipt_for,
)
from labkit.report import eligible
from labkit.runner import make_submission, sync_grades


def git(folder, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=folder, text=True, capture_output=True, check=check
    )


class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.teacher = self.root / "teacher"
        git(self.root, "clone", str(self.remote), str(self.teacher))
        self.identity(self.teacher)
        (self.teacher / "README.md").write_text("Course materials\n")
        (self.teacher / ".gitignore").write_text("config.json\nruns/\n")
        git(self.teacher, "add", ".")
        git(self.teacher, "commit", "-m", "Course baseline")
        git(self.teacher, "push", "origin", "main")
        self.student = self.root / "student"
        git(self.root, "clone", str(self.remote), str(self.student))
        self.identity(self.student)
        self.cfg = {"repository": str(self.remote), "participant": "p01"}

    def identity(self, folder):
        git(folder, "config", "user.name", "Fixture")
        git(folder, "config", "user.email", "fixture@example.invalid")
        git(folder, "config", "commit.gpgsign", "false")

    def tearDown(self):
        self.tmp.cleanup()

    def artifact(self):
        folder = self.student / "runs/20261109-000000-abcd"
        folder.mkdir(parents=True, exist_ok=True)
        path = self.student / "submissions" / (folder.name + ".zip")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"fixture submission")
        return folder, path

    def test_enrollment_selects_only_assigned_branch(self):
        self.assertEqual(enroll(self.student, self.cfg, "P01"), "students/p01")
        self.assertEqual(
            git(self.student, "branch", "--show-current").stdout.strip(), "students/p01"
        )
        self.assertEqual(
            json.loads((self.student / "config.json").read_text())["participant"], "p01"
        )

    def test_unsafe_participant_name_is_rejected(self):
        for name in ["../../main", "p01/a", "-x", ""]:
            with self.assertRaises(ValueError):
                participant(name)

    def test_main_cannot_be_used_for_submission(self):
        folder, path = self.artifact()
        with self.assertRaises(ValueError):
            push_submission(self.student, folder, path, self.cfg)
        self.assertEqual(
            git(self.student, "branch", "--show-current").stdout.strip(), "main"
        )

    def test_only_generated_artifact_is_committed(self):
        enroll(self.student, self.cfg, "p01")
        folder, path = self.artifact()
        (self.student / "local-notes.txt").write_text("Do not publish")
        result = push_submission(self.student, folder, path, self.cfg)
        files = git(
            self.remote, "ls-tree", "-r", "--name-only", "refs/heads/students/p01"
        ).stdout
        self.assertIn("submissions/" + folder.name + ".zip", files)
        self.assertNotIn("local-notes.txt", files)
        self.assertNotIn("config.json", files)
        self.assertEqual(result["branch"], "students/p01")

    def test_other_staged_files_stop_submission(self):
        enroll(self.student, self.cfg, "p01")
        folder, path = self.artifact()
        (self.student / "other.txt").write_text("unrelated")
        git(self.student, "add", "other.txt")
        with self.assertRaises(ValueError):
            push_submission(self.student, folder, path, self.cfg)

    def test_result_is_bound_to_exact_submitted_git_blob(self):
        enroll(self.student, self.cfg, "p01")
        folder, path = self.artifact()
        submitted = push_submission(self.student, folder, path, self.cfg)
        git(self.teacher, "checkout", "--orphan", "results")
        grade = self.teacher / "grades/p01" / f"{folder.name}.json"
        grade.parent.mkdir(parents=True)
        grade.write_text(
            json.dumps(
                {
                    "run_id": folder.name,
                    "artifact_blob": submitted["artifact_blob"],
                    "status": "passed",
                }
            )
        )
        git(self.teacher, "add", "grades")
        git(self.teacher, "commit", "-m", "Fixture receipt")
        git(self.teacher, "push", "origin", "results")
        fetch_results(self.student, self.cfg)
        self.assertEqual(
            receipt_for(self.student, folder, self.cfg)["status"], "passed"
        )
        path.write_bytes(b"new submission")
        push_submission(self.student, folder, path, self.cfg)
        self.assertIsNone(receipt_for(self.student, folder, self.cfg))

    def test_origin_must_match_the_course_repository(self):
        with self.assertRaises(ValueError):
            enroll(
                self.student,
                {**self.cfg, "repository": "https://github.com/other/course.git"},
                "p01",
            )

    def test_submission_preflight_does_not_create_a_remote_branch(self):
        enroll(self.student, self.cfg, "p01")
        self.assertEqual(check_submission_ready(self.student, self.cfg), "students/p01")
        self.assertNotEqual(
            git(
                self.remote, "rev-parse", "--verify", "students/p01", check=False
            ).returncode,
            0,
        )

    def test_submission_preflight_requires_git_identity(self):
        enroll(self.student, self.cfg, "p01")
        git(self.student, "config", "user.email", "")
        with self.assertRaisesRegex(ValueError, "user.email"):
            check_submission_ready(self.student, self.cfg)

    def test_sync_invalidates_a_saved_grade_after_manual_resubmission(self):
        enroll(self.student, self.cfg, "p01")
        folder, artifact = self.artifact()
        source = folder / "workspace/src/example.py"
        source.parent.mkdir(parents=True)
        source.write_text("pass\n")
        summary = {
            "id": folder.name,
            "label": "fixture",
            "execution_status": "completed",
            "comparison_valid": True,
            "condition_id": "fixture",
            "source_sha256": source_digest(folder / "workspace"),
            "usage": {"input_tokens": 100, "document_candidates": [], "calls": []},
            "grade": {"status": "pending"},
        }
        write_json(folder / "summary.json", summary)
        submitted = push_submission(self.student, folder, artifact, self.cfg)
        git(self.teacher, "checkout", "--orphan", "results")
        write_json(
            self.teacher / "grades/p01" / (folder.name + ".json"),
            {
                "run_id": folder.name,
                "source_sha256": summary["source_sha256"],
                "artifact_blob": submitted["artifact_blob"],
                "status": "passed",
            },
        )
        git(self.teacher, "add", "grades")
        git(self.teacher, "commit", "-m", "fixture grade")
        git(self.teacher, "push", "origin", "results")
        self.assertEqual(sync_grades(self.student, self.cfg), 1)
        self.assertTrue(eligible(json.loads((folder / "summary.json").read_text())))
        artifact.write_bytes(b"replacement submission")
        # A locally changed ZIP must not borrow the committed ZIP's grade either.
        self.assertIsNone(receipt_for(self.student, folder, self.cfg))
        push_submission(self.student, folder, artifact, self.cfg)
        self.assertEqual(sync_grades(self.student, self.cfg), 0)
        saved = json.loads((folder / "summary.json").read_text())
        self.assertEqual(saved["grade"]["status"], "pending")
        self.assertFalse(eligible(saved))

    def test_repackaging_resets_status_only_when_artifact_changes(self):
        folder, _ = self.artifact()
        source = folder / "workspace/src/example.py"
        source.parent.mkdir(parents=True)
        source.write_text("pass\n")
        summary = {
            "id": folder.name,
            "protected_before": {},
            "grade": {"status": "pending"},
        }
        archive = make_submission(self.student, folder, summary)
        summary.update(
            submission_status="submitted",
            grade={
                "status": "passed",
                "artifact_blob": git(
                    self.student, "hash-object", str(archive)
                ).stdout.strip(),
            },
        )
        make_submission(self.student, folder, summary)
        self.assertEqual(summary["submission_status"], "submitted")
        self.assertEqual(summary["grade"]["status"], "passed")
        summary["note"] = "changed explanation"
        make_submission(self.student, folder, summary)
        self.assertEqual(summary["submission_status"], "not_submitted")
        self.assertEqual(summary["grade"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
