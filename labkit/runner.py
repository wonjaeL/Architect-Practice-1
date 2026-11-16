from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path

from .common import (
    digest,
    extract_zip,
    read_json,
    run_process,
    source_digest,
    write_json,
)
from .preflight import Check, execution_checks, require_checks
from .report import render_report
from .usage import parse_usage

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "baseline": "기본 작업 지침",
    "disclosure": "Progressive disclosure 적용",
    "custom": "직접 개선",
}
DEFAULTS = {
    "participant": None,
    "codex_command": ["codex"],
    "model": None,
    "profile": None,
    "reasoning_effort": None,
    "timeout_seconds": 900,
    "repository": "https://github.com/legenduck/Architect-Practice-1.git",
}


def protected_files(workspace: Path) -> dict:
    paths = set(workspace.rglob("AGENTS*.md"))
    for name in ["data", "docs", ".agents/skills"]:
        paths.update((workspace / name).rglob("*"))
    paths.add(workspace / "tools/test_summary.py")
    return {
        p.relative_to(workspace).as_posix(): digest(p)
        for p in sorted(paths)
        if p.is_file() and not p.is_symlink()
    }


def config(root: Path) -> dict:
    path = root / "config.json"
    example = root / "config.example.json"
    cfg = {
        **DEFAULTS,
        **(read_json(example) if example.exists() else {}),
        **(read_json(path) if path.exists() else {}),
    }
    if (
        not isinstance(cfg["codex_command"], list)
        or not cfg["codex_command"]
        or not all(isinstance(x, str) for x in cfg["codex_command"])
    ):
        raise ValueError("codex_command는 실행 파일과 인자를 담은 목록이어야 합니다.")
    if (
        type(cfg["timeout_seconds"]) is not int
        or not 1 <= cfg["timeout_seconds"] <= 3600
    ):
        raise ValueError("실행 제한 시간은 1~3600초 범위여야 합니다.")
    if cfg["model"] is not None and (
        not isinstance(cfg["model"], str) or not cfg["model"].strip()
    ):
        raise ValueError("model은 연구원이 지정한 모델 이름이어야 합니다.")
    if cfg["reasoning_effort"] not in (
        None,
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    ):
        raise ValueError("reasoning_effort 설정을 확인하세요.")
    return cfg


def checked_copy(src: Path, dst: Path) -> None:
    if src.is_symlink():
        raise ValueError("작업 지침에는 심볼릭 링크를 사용할 수 없습니다.")
    if src.is_dir():
        for path in src.rglob("*"):
            if path.is_symlink():
                raise ValueError("스킬에는 심볼릭 링크를 사용할 수 없습니다.")
        shutil.copytree(src, dst)
    else:
        shutil.copyfile(src, dst)


def initialize(root: Path) -> None:
    edit = root / "edit"
    if not edit.exists():
        edit.mkdir()
        extract_zip((root / "assets/parkfee.zip").read_bytes(), edit)
        shutil.copyfile(root / "instructions/AGENTS.example.md", edit / "AGENTS.md")
        (edit / "tools").mkdir(exist_ok=True)
        shutil.copyfile(root / "labkit/test_summary.py", edit / "tools/test_summary.py")
    if not (root / "config.json").exists():
        write_json(root / "config.json", config(root))
    render_report(root)
    print("작업 폴더 확인. 직접 개선할 작업 지침:", edit / "AGENTS.md")


def prepare_run(root: Path, variant: str, cfg: dict) -> tuple[Path, dict]:
    identifier = datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + uuid.uuid4().hex[:8]
    folder = root / "runs" / identifier
    workspace = folder / "workspace"
    workspace.mkdir(parents=True)
    extract_zip((root / "assets/parkfee.zip").read_bytes(), workspace)
    (workspace / "tools").mkdir(exist_ok=True)
    shutil.copyfile(
        root / "labkit/test_summary.py", workspace / "tools/test_summary.py"
    )
    if variant == "custom":
        instructions = root / "edit/AGENTS.md"
        if not instructions.is_file():
            raise ValueError("먼저 python lab.py init을 실행하세요.")
    else:
        instructions = (
            root
            / "instructions"
            / ("AGENTS.baseline.md" if variant == "baseline" else "AGENTS.example.md")
        )
    checked_copy(instructions, workspace / "AGENTS.md")
    if variant == "custom" and (root / "edit/.agents/skills").exists():
        (workspace / ".agents").mkdir(exist_ok=True)
        checked_copy(root / "edit/.agents/skills", workspace / ".agents/skills")
    snapshot = folder / "instructions"
    snapshot.mkdir()
    shutil.copyfile(workspace / "AGENTS.md", snapshot / "AGENTS.md")
    if (workspace / ".agents/skills").exists():
        shutil.copytree(workspace / ".agents/skills", snapshot / "skills")
    # No global Git configuration or caller identity is changed.
    subprocess.run(
        ["git", "init", "-q", str(workspace)], check=True, capture_output=True
    )
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Practice 1",
            "-c",
            "user.email=practice1@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            f"core.hooksPath={workspace / '.git/hooks'}",
            "commit",
            "-qm",
            "Practice 1 initial state",
        ],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    conditions = {
        "baseline_sha256": digest(root / "assets/parkfee.zip"),
        "request_sha256": digest(root / "task/request.md"),
        "test_helper_sha256": digest(root / "labkit/test_summary.py"),
        "model": cfg["model"] or "CLI 기본 설정",
        "profile": cfg["profile"],
        "reasoning_effort": cfg.get("reasoning_effort"),
        "codex_command": cfg["codex_command"],
        "timeout_seconds": cfg["timeout_seconds"],
    }
    summary = {
        "schema": 1,
        "id": identifier,
        "participant": cfg["participant"],
        "variant": variant,
        "label": LABELS[variant],
        "conditions": conditions,
        "instructions_sha256": digest(snapshot / "AGENTS.md"),
        "protected_before": protected_files(workspace),
        "initial_source_sha256": source_digest(workspace),
        "comparison_valid": True,
        "execution_status": "prepared",
        "grade": {"status": "pending"},
        "submission_status": "not_submitted",
        "techniques": [],
        "note": "",
        "usage": parse_usage(folder / "events.jsonl"),
    }
    write_json(folder / "summary.json", summary)
    return folder, summary


def find_rollout(thread: str | None) -> Path | None:
    if not thread or not all(c.isalnum() or c == "-" for c in thread):
        return None
    # Only look for this execution's thread ID, never ingest other conversations.
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    found = list((home / "sessions").glob(f"**/*{thread}*.jsonl"))
    return found[0] if len(found) == 1 else None


def make_submission(root: Path, folder: Path, summary: dict) -> Path:
    workspace = folder / "workspace"
    sha = source_digest(workspace)
    if summary.get("source_sha256") and summary["source_sha256"] != sha:
        summary["grade"] = {
            "status": "pending",
            "message": "채점 후 소스가 변경되어 재채점이 필요합니다.",
        }
        summary["comparison_valid"] = False
        summary["comparison_message"] = (
            "실행 종료 후 소스가 변경되어 기존 토큰 기록과 비교할 수 없습니다. 새로 실행하세요."
        )
    if protected_files(workspace) != summary.get("protected_before"):
        summary["comparison_valid"] = False
        summary["comparison_message"] = (
            "실행 지침, 문서, 데이터 또는 테스트 보조 도구가 변경되어 비교에서 제외합니다."
        )
    summary["source_sha256"] = sha
    write_json(folder / "summary.json", summary)
    target = root / "submissions" / (summary["id"] + ".zip")
    target.parent.mkdir(exist_ok=True)
    previous_archive = digest(target) if target.exists() else None
    files = [(folder / "summary.json", "summary.json")]
    for prefix in ["src", "tests"]:
        for path in sorted((workspace / prefix).rglob("*.py")):
            if path.is_symlink():
                raise ValueError("제출 파일에는 심볼릭 링크를 사용할 수 없습니다.")
            files.append((path, "workspace/" + path.relative_to(workspace).as_posix()))
    for path in sorted((folder / "instructions").rglob("*")):
        if path.is_file():
            files.append((path, path.relative_to(folder).as_posix()))
    # Only this task's JSONL, not auth files, environment variables or home files.
    for name in ["events.jsonl"]:
        if (folder / name).exists():
            files.append((folder / name, name))
    if sum(p.stat().st_size for p, _ in files) > 15_000_000:
        raise ValueError("제출 파일이 15MB를 넘었습니다. 연구원에게 확인을 요청하세요.")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            raw = path.read_bytes()
            if name == "summary.json":
                payload = dict(summary)
                for key in ("grade", "submission_status", "submission_error"):
                    payload.pop(key, None)
                raw = json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, indent=2
                ).encode()
            archive.writestr(info, raw)
    if digest(target) != previous_archive:
        summary["submission_status"] = "not_submitted"
        summary.pop("submission_error", None)
    # Local metadata belongs to the current ZIP, even if a later push fails.
    if summary.get("grade", {}).get("status") in ("passed", "failed", "error"):
        from .github_flow import git

        blob = git(root, "hash-object", "--", str(target)).stdout.strip()
        if blob != summary["grade"].get("artifact_blob"):
            summary["grade"] = {
                "status": "pending",
                "message": "제출 파일이 변경되어 새 채점 결과가 필요합니다.",
            }
    write_json(folder / "summary.json", summary)
    return target


def prepare_submission(root: Path, folder: Path, summary: dict) -> None:
    summary["grade"] = {
        "status": "pending",
        "message": "GitHub 제출 후 중앙 채점 결과를 받아야 합니다.",
    }
    make_submission(root, folder, summary)
    write_json(folder / "summary.json", summary)


def sync_grades(root: Path, cfg: dict) -> int:
    from .github_flow import fetch_results, receipt_for

    fetch_results(root, cfg)
    count = 0
    for path in sorted((root / "runs").glob("*/summary.json")):
        folder = path.parent
        summary = read_json(path)
        receipt = receipt_for(root, folder, cfg)
        if receipt is None:
            if summary.get("grade", {}).get("status") in ("passed", "failed", "error"):
                summary["grade"] = {
                    "status": "pending",
                    "message": "현재 제출 파일과 일치하는 채점 결과가 없습니다.",
                }
                write_json(path, summary)
            continue
        if source_digest(folder / "workspace") != summary.get("source_sha256"):
            summary["comparison_valid"] = False
            summary["comparison_message"] = (
                "실행 후 소스가 변경되어 비교에서 제외합니다."
            )
        apply_grade(summary, receipt)
        summary["submission_status"] = "submitted"
        write_json(path, summary)
        count += 1
    render_report(root)
    return count


def submit_github(
    root: Path, folder: Path, cfg: dict, summary: dict, wait_seconds: int = 0
) -> None:
    from .github_flow import push_submission

    if summary.get("execution_status") != "completed":
        raise ValueError(
            "정상 종료하고 소스를 변경한 실행만 제출할 수 있습니다. 실행 로그를 확인하세요."
        )
    initial = summary.get("initial_source_sha256")
    if initial is None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary)
            extract_zip((root / "assets/parkfee.zip").read_bytes(), baseline)
            initial = source_digest(baseline)
    if source_digest(folder / "workspace") == initial:
        raise ValueError(
            "초기 코드에서 소스 변경이 없습니다. 구현을 수행한 뒤 새로 실행하세요."
        )

    archive = make_submission(root, folder, summary)
    try:
        status = push_submission(root, folder, archive, cfg)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        summary.update(submission_status="failed", submission_error=str(error))
        write_json(folder / "summary.json", summary)
        render_report(root)
        raise
    print("GitHub 제출 완료:", status["branch"], status["commit"][:12])
    summary["grade"] = {"status": "pending", "message": "중앙 채점 대기"}
    summary["submission_status"] = "submitted"
    summary.pop("submission_error", None)
    write_json(folder / "summary.json", summary)
    deadline = time.monotonic() + min(max(wait_seconds, 0), 180)
    while wait_seconds > 0:
        sync_grades(root, cfg)
        current = read_json(folder / "summary.json")
        if current["grade"]["status"] != "pending":
            print("채점 결과:", current["grade"]["status"])
            break
        if time.monotonic() >= deadline:
            print("채점 대기 중입니다. python lab.py sync로 나중에 다시 확인하세요.")
            break
        time.sleep(min(10, max(0, deadline - time.monotonic())))
    render_report(root)


def apply_grade(summary: dict, receipt: dict) -> None:
    if (
        receipt.get("run_id") != summary["id"]
        or receipt.get("source_sha256") != summary["source_sha256"]
    ):
        raise ValueError("채점 결과가 이 실행의 소스와 일치하지 않습니다.")
    if receipt.get("status") not in ("passed", "failed", "error"):
        raise ValueError("알 수 없는 채점 상태입니다.")
    summary["grade"] = receipt


def execute(root: Path, variant: str, cfg: dict, *, prechecked: bool = False) -> Path:
    if not cfg["model"]:
        raise ValueError("config.json의 model을 연구원이 지정한 값으로 설정하세요.")
    if not prechecked:
        require_checks(execution_checks(root, cfg))
    folder, summary = prepare_run(root, variant, cfg)
    started = time.monotonic()
    command = list(cfg["codex_command"])
    try:
        version = subprocess.run(
            command + ["--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        summary["conditions"]["codex_version"] = version.stdout.strip()
        conditions = json.dumps(summary["conditions"], sort_keys=True).encode()
        summary["condition_id"] = hashlib.sha256(conditions).hexdigest()
        command += [
            "-a",
            "never",
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "-C",
            str(folder / "workspace"),
            "-o",
            str(folder / "last-message.txt"),
        ]
        if cfg["model"]:
            command += ["--model", cfg["model"]]
        if cfg["profile"]:
            command += ["--profile", cfg["profile"]]
        if cfg.get("reasoning_effort"):
            command += [
                "-c",
                'model_reasoning_effort="' + cfg["reasoning_effort"] + '"',
            ]
        command.append("-")
        env = dict(os.environ)
        # Use the user's Codex account session, not a direct model API key.
        env.pop("OPENAI_API_KEY", None)
        env.pop("CODEX_API_KEY", None)
        code = run_process(
            command,
            folder / "workspace",
            folder / "events.jsonl",
            folder / "codex-stderr.txt",
            cfg["timeout_seconds"],
            (root / "task/request.md").read_text(encoding="utf-8"),
            env,
        )
        summary["exit_code"] = code
        summary["execution_status"] = "completed" if code == 0 else "failed"
    except subprocess.TimeoutExpired:
        summary["execution_status"] = "timeout"
    except KeyboardInterrupt:
        summary["execution_status"] = "interrupted"
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        summary["execution_status"] = "error"
        summary["error"] = str(error)
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    usage = parse_usage(folder / "events.jsonl")
    try:
        rollout = find_rollout(usage["thread_id"])
        if rollout:
            usage = parse_usage(folder / "events.jsonl", rollout)
    except OSError:
        summary["measurement_message"] = (
            "호출별 세션 기록에 접근할 수 없어 실행 총량만 표시합니다."
        )
    summary["usage"] = usage
    try:
        summary["source_changed"] = (
            source_digest(folder / "workspace") != summary["initial_source_sha256"]
        )
    except (OSError, ValueError) as error:
        summary["execution_status"] = "error"
        summary["source_changed"] = None
        summary["error"] = "실행 후 소스를 확인하지 못했습니다: " + str(error)
    if summary["execution_status"] == "completed":
        if (
            usage["failed_event"]
            or usage["completed_turns"] != 1
            or usage["malformed_lines"]
        ):
            summary["execution_status"] = "failed"
            summary["error"] = (
                "정상 완료 이벤트를 확인하지 못했습니다. 원본 실행 로그를 확인하세요."
            )
        elif not summary["source_changed"]:
            summary["execution_status"] = "no_changes"
            summary["error"] = (
                "초기 코드에서 소스 변경이 없습니다. Codex 최종 응답과 명령 실행 오류를 확인하세요."
            )
    if usage["input_tokens"] is None:
        summary["measurement_message"] = (
            "총 입력 토큰을 확인할 수 없어 토큰 절감 비교에서 제외합니다."
        )
    summary["comparison_valid"] = (
        protected_files(folder / "workspace") == summary["protected_before"]
    )
    if not summary["comparison_valid"]:
        summary["comparison_message"] = (
            "실행 중 지침, 문서, 데이터 또는 테스트 보조 도구가 변경되어 비교에서 제외합니다."
        )
    write_json(folder / "summary.json", summary)
    try:
        if summary["execution_status"] == "completed":
            prepare_submission(root, folder, summary)
    except (OSError, ValueError) as error:
        summary["grade"] = {"status": "error", "message": str(error)}
        write_json(folder / "summary.json", summary)
    render_report(root)
    print("실행", summary["id"], "/", summary["execution_status"])
    print("결과:", root / "results.html")
    return folder


def get_run(root: Path, run_id: str) -> Path:
    if run_id == "latest":
        paths = sorted((root / "runs").glob("*/summary.json"))
        if not paths:
            raise ValueError("실행 기록이 없습니다.")
        return paths[-1].parent
    if not run_id or any(c not in "0123456789-abcdef" for c in run_id):
        raise ValueError("실행 ID가 올바르지 않습니다.")
    folder = root / "runs" / run_id
    if not (folder / "summary.json").exists():
        raise ValueError("실행 기록을 찾지 못했습니다.")
    return folder


def doctor(
    root: Path,
    *,
    cfg: dict | None = None,
    submission: bool = True,
    include_login: bool = True,
) -> bool:
    cfg = config(root) if cfg is None else cfg
    checks = execution_checks(root, cfg, include_login=include_login)
    if submission:
        from .github_flow import check_submission_ready

        try:
            check_submission_ready(root, cfg, require_enrollment=False)
            checks.append(Check("Git 제출 접속", True))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            checks.append(
                Check(
                    "Git 제출 접속",
                    False,
                    str(error),
                    "Git 인증·제출자 정보와 저장소 참여 설정을 확인하세요.",
                )
            )
    for check in checks:
        print("[OK]" if check.ok else "[FAIL]", check.name)
        if not check.ok:
            hint = check.fix or next(
                iter(check.detail.splitlines()), "doctor.log를 확인하세요."
            )
            print("  " + hint[:180])
    (root / "doctor.log").write_text(
        "\n\n".join(
            f"{'OK' if c.ok else 'FAIL'} {c.name}\n{c.detail}\n{c.fix}" for c in checks
        ),
        encoding="utf-8",
    )
    ok = all(check.ok for check in checks)
    print(
        "준비 완료. 시작 파일을 실행하면 실습 메뉴가 열립니다."
        if ok
        else "준비 확인이 필요합니다. 상세 내용: doctor.log"
    )
    return ok


def run_menu(root: Path, *, ready_config: dict | None = None) -> None:
    from .github_flow import submission_branch

    ready_config = dict(ready_config) if ready_config is not None else None
    while True:
        print(
            "\n1 기본 지침 실행·제출\n2 Progressive disclosure 실행·제출\n3 직접 개선 실행·제출\n4 결과 보기\n5 최근 실행 제출·재제출\n6 채점 결과 가져오기\n7 doctor\n0 종료"
        )
        try:
            choice = input("번호: ").strip()
            if choice == "0":
                return
            cfg = config(root)
            if choice in ("1", "2", "3"):
                submission_branch(root, cfg)
                if cfg != ready_config:
                    if not doctor(root, cfg=cfg):
                        continue
                    ready_config = dict(cfg)
                folder = execute(
                    root,
                    ["baseline", "disclosure", "custom"][int(choice) - 1],
                    cfg,
                    prechecked=True,
                )
                summary = read_json(folder / "summary.json")
                if summary["execution_status"] == "completed":
                    submit_github(root, folder, cfg, summary)
                    print("6번으로 채점 결과를 가져오세요.")
                else:
                    ready_config = None
            elif choice == "5":
                folder = get_run(root, "latest")
                summary = read_json(folder / "summary.json")
                techniques = input("적용한 기법(쉼표 구분, Enter로 유지): ").strip()
                note = input("변경 내용(Enter로 유지): ").strip()
                if techniques:
                    summary["techniques"] = [
                        x.strip() for x in techniques.split(",") if x.strip()
                    ]
                if note:
                    summary["note"] = note
                submit_github(root, folder, cfg, summary)
            elif choice == "6":
                print("반영한 채점 결과:", sync_grades(root, cfg))
            elif choice == "7":
                ready_config = dict(cfg) if doctor(root, cfg=cfg) else None
                continue
            elif choice != "4":
                print("0~7 중에서 선택하세요.")
                continue
            webbrowser.open(render_report(root).as_uri())
        except EOFError:
            return
        except KeyboardInterrupt:
            print("취소했습니다. 메뉴에서 이어서 진행할 수 있습니다.")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            ready_config = None
            print(
                f"확인 필요: {error}\n기록은 보존했습니다. 해결 후 메뉴에서 다시 시도하세요."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("init")
    sub.add_parser("doctor")
    sub.add_parser("report")
    enrollment = sub.add_parser("enroll")
    enrollment.add_argument("participant")
    sub.add_parser("sync")
    run = sub.add_parser("run")
    run.add_argument("variant", choices=LABELS)
    run.add_argument("--submit", action="store_true")
    run.add_argument("--wait", type=int, default=0)
    submit = sub.add_parser("submit")
    submit.add_argument("--run", default="latest")
    submit.add_argument("--technique", action="append", default=[])
    submit.add_argument("--note", default="")
    submit.add_argument("--wait", type=int, default=0)
    load = sub.add_parser("import-grade")
    load.add_argument("receipt", type=Path)
    args = parser.parse_args()
    root = ROOT
    try:
        if args.action is None:
            initialize(root)
            run_menu(root)
        elif args.action == "init":
            initialize(root)
        elif args.action == "enroll":
            from .github_flow import enroll

            print("실습 브랜치:", enroll(root, config(root), args.participant))
        elif args.action == "sync":
            print("반영한 채점 결과:", sync_grades(root, config(root)))
        elif args.action == "doctor":
            sys.exit(0 if doctor(root) else 1)
        elif args.action == "run":
            if args.submit:
                from .github_flow import check_submission_ready

                check_submission_ready(root, config(root))
            folder = execute(root, args.variant, config(root))
            summary = read_json(folder / "summary.json")
            if summary["execution_status"] != "completed":
                sys.exit(1)
            if args.submit:
                submit_github(root, folder, config(root), summary, args.wait)
        elif args.action == "report":
            print(render_report(root))
        elif args.action == "submit":
            folder = get_run(root, args.run)
            summary = read_json(folder / "summary.json")
            summary.update(techniques=args.technique, note=args.note)
            submit_github(root, folder, config(root), summary, args.wait)
        elif args.action == "import-grade":
            receipt = read_json(args.receipt)
            folder = get_run(root, receipt["run_id"])
            summary = read_json(folder / "summary.json")
            if source_digest(folder / "workspace") != summary.get("source_sha256"):
                raise ValueError("실행 후 소스가 변경되었습니다. 재채점이 필요합니다.")
            apply_grade(summary, receipt)
            write_json(folder / "summary.json", summary)
            print(render_report(root))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"확인 필요: {error}\n")
