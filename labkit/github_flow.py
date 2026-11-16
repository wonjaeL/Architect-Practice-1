"""GitHub branch submission. No model API or GitHub API token is needed here."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .common import write_json

REPOSITORY = "https://github.com/legenduck/Architect-Practice-1.git"
BRANCH_PREFIX = "students/"
RESULTS_BRANCH = "results"


def participant(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("먼저 배정받은 참가자 번호로 실습을 시작하세요.")
    identifier = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", identifier):
        raise ValueError("참가자 번호는 p01처럼 영문 소문자와 숫자로 입력하세요.")
    return identifier


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
    )
    if check and done.returncode:
        raise ValueError("Git 명령을 완료하지 못했습니다.\n" + done.stderr.strip())
    return done


def canonical(url: str) -> str:
    value = url.strip().rstrip("/")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.split(":", 1)[1]
    parts = urlparse(value)
    if parts.scheme in ("https", "http") and (parts.username or parts.password):
        raise ValueError(
            "저장소 주소에 인증 정보를 넣지 마세요. Git 로그인 도구를 사용하세요."
        )
    return value.removesuffix(".git").lower()


def verify_remote(root: Path, repository: str) -> None:
    actual = git(root, "remote", "get-url", "origin").stdout.strip()
    if canonical(actual) != canonical(repository):
        raise ValueError(
            "origin이 교육용 저장소와 다릅니다. 연구원에게 확인을 요청하세요."
        )


def enroll(root: Path, cfg: dict, identifier: str) -> str:
    identifier = participant(identifier)
    verify_remote(root, cfg.get("repository", REPOSITORY))
    branch = BRANCH_PREFIX + identifier
    current = git(root, "branch", "--show-current").stdout.strip()
    if current != branch:
        if git(root, "status", "--porcelain").stdout.strip():
            raise ValueError(
                "저장소에 변경사항이 있습니다. 내용을 보존한 채 연구원에게 브랜치 전환을 요청하세요."
            )
        git(root, "fetch", "origin")
        if (
            git(
                root,
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/" + branch,
                check=False,
            ).returncode
            == 0
        ):
            git(root, "switch", branch)
        elif (
            git(
                root,
                "show-ref",
                "--verify",
                "--quiet",
                "refs/remotes/origin/" + branch,
                check=False,
            ).returncode
            == 0
        ):
            git(root, "switch", "--track", "-c", branch, "origin/" + branch)
        else:
            git(root, "switch", "-c", branch, "origin/main")
    cfg.update(participant=identifier, repository=cfg.get("repository", REPOSITORY))
    write_json(root / "config.json", cfg)
    return branch


def submission_branch(root: Path, cfg: dict) -> str:
    verify_remote(root, cfg.get("repository", REPOSITORY))
    identifier = participant(cfg["participant"])
    branch = BRANCH_PREFIX + identifier
    if git(root, "branch", "--show-current").stdout.strip() != branch:
        raise ValueError(
            f"먼저 python lab.py enroll {identifier}로 개인 브랜치를 선택하세요. main에는 제출하지 않습니다."
        )
    return branch


def check_submission_ready(
    root: Path, cfg: dict, *, require_enrollment: bool = True
) -> str:
    """Check identity and remote access without creating a commit or remote ref."""
    if require_enrollment:
        branch = submission_branch(root, cfg)
    else:
        verify_remote(root, cfg.get("repository", REPOSITORY))
        branch = (
            BRANCH_PREFIX + participant(cfg["participant"])
            if cfg.get("participant")
            else None
        )
        if git(root, "branch", "--show-current").stdout.strip() != branch:
            if git(root, "status", "--porcelain").stdout.strip():
                raise ValueError(
                    "저장소 변경사항을 먼저 정리하세요. 직접 개선할 지침은 edit/AGENTS.md입니다."
                )
            # Enrollment may resume an existing remote branch after this check.
            # Probe access without trying to replace its history with local main.
            branch = BRANCH_PREFIX + "doctor-" + uuid.uuid4().hex[:8]
    for key in ("user.name", "user.email"):
        if not git(root, "config", "--get", key, check=False).stdout.strip():
            raise ValueError(
                f'Git {key}가 없습니다. git config --local {key} "본인 정보"로 설정하세요.'
            )
    git(root, "push", "--dry-run", "--porcelain", "origin", "HEAD:refs/heads/" + branch)
    return branch


def push_submission(root: Path, folder: Path, archive: Path, cfg: dict) -> dict:
    branch = submission_branch(root, cfg)
    identifier = participant(cfg["participant"])
    relative = archive.resolve().relative_to(root.resolve()).as_posix()
    staged = git(root, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
    if any(name and name != relative for name in staged):
        raise ValueError(
            "다른 파일이 커밋 대상으로 지정되어 있습니다. 해당 변경을 먼저 확인하세요."
        )
    git(root, "add", "--", relative)
    if git(root, "diff", "--cached", "--quiet", "--", relative, check=False).returncode:
        git(root, "commit", "-m", "Submit practice 1 run " + folder.name)
    git(root, "push", "-u", "origin", "HEAD:refs/heads/" + branch)
    commit = git(root, "rev-parse", "HEAD").stdout.strip()
    blob = git(root, "rev-parse", "HEAD:" + relative).stdout.strip()
    status = {
        "participant": identifier,
        "branch": branch,
        "commit": commit,
        "artifact_blob": blob,
        "path": relative,
        "run_id": folder.name,
    }
    write_json(folder / "github-status.json", status)
    return status


def fetch_results(root: Path, cfg: dict) -> None:
    verify_remote(root, cfg.get("repository", REPOSITORY))
    git(
        root,
        "fetch",
        "origin",
        f"refs/heads/{RESULTS_BRANCH}:refs/remotes/origin/{RESULTS_BRANCH}",
    )


def check_results_ready(root: Path, cfg: dict) -> None:
    """Verify the instructor has run the publisher before students start."""
    fetch_results(root, cfg)
    response = git(root, "show", "origin/results:service.json", check=False)
    if response.returncode:
        raise ValueError(
            "강사가 자동 채점을 한 번 실행해 결과 수신 경로를 준비해야 합니다."
        )
    service = json.loads(response.stdout)
    if service.get("schema") != 1 or not service.get("grader"):
        raise ValueError("채점 서비스 정보가 올바르지 않습니다.")


def receipt_for(root: Path, folder: Path, cfg: dict) -> dict | None:
    identifier = participant(cfg["participant"])
    path = f"grades/{identifier}/{folder.name}.json"
    response = git(root, "show", f"origin/{RESULTS_BRANCH}:{path}", check=False)
    if response.returncode:
        return None
    receipt = json.loads(response.stdout)
    artifact = f"submissions/{folder.name}.zip"
    recorded = git(root, "rev-parse", f"HEAD:{artifact}", check=False)
    if recorded.returncode or receipt.get("artifact_blob") != recorded.stdout.strip():
        return (
            None  # A new submission is awaiting grading; do not reuse an older grade.
        )
    local = git(root, "hash-object", "--", artifact, check=False)
    if local.returncode or local.stdout.strip() != recorded.stdout.strip():
        return None
    return receipt
