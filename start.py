"""수강생용 시작점. Python 이외의 Python 패키지는 자동으로 준비합니다."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def environment_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def bootstrap(root: Path) -> Path:
    python = environment_python(root)
    if not python.exists():
        print("실습용 Python 환경을 준비합니다.", flush=True)
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
    requirements = root / "requirements-lab.txt"
    expected = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = root / ".venv/.lab-requirements.sha256"
    if not stamp.exists() or stamp.read_text() != expected:
        print(
            "실습에 필요한 패키지를 설치합니다. 첫 준비에는 네트워크 연결이 필요합니다.",
            flush=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements)],
            cwd=root,
            check=True,
        )
        stamp.write_text(expected)
    return python


def answer(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise ValueError(
            "최초 설정에는 터미널 입력이 필요합니다. start.bat 또는 start.command를 열어 주세요."
        )
    value = input(prompt).strip()
    if not value:
        raise ValueError("빈 값으로 설정하지 않았습니다. 시작 파일을 다시 실행하세요.")
    return value


def launch(root: Path, args: argparse.Namespace) -> int:
    from labkit.common import write_json
    from labkit.github_flow import enroll, git, participant
    from labkit.preflight import command_check
    from labkit.runner import config, doctor, initialize
    from labkit.runner import main as lab_main

    cfg = config(root)
    if args.model:
        if not args.prepare:
            raise ValueError("모델 변경은 강사용 --prepare에서만 지정하세요.")
        cfg["model"] = args.model
    if args.reasoning_effort:
        if not args.prepare:
            raise ValueError("추론 설정 변경은 강사용 --prepare에서만 지정하세요.")
        cfg["reasoning_effort"] = args.reasoning_effort
    if args.prepare:
        if not cfg["model"]:
            raise ValueError(
                "강사가 --prepare --model 모델명으로 과제 실행 모델을 지정해야 합니다."
            )
        write_json(root / "config.json", cfg)
        initialize(root)
        ok = doctor(root, include_login=False)
        if ok:
            print(
                "공통 환경 준비 완료. 수강생은 시작 파일을 실행해 본인 로그인·참가자 번호·Git 제출 준비를 확인합니다."
            )
        return 0 if ok else 1
    initialize(root)
    if args.check:
        return 0 if doctor(root, submission=True) else 1
    if not cfg["model"]:
        raise ValueError(
            "강사용 모델 설정이 없습니다. 연구원이 start.py --prepare --model 모델명으로 먼저 준비해야 합니다."
        )
    # Fail on host incompatibilities before asking a learner to authenticate.
    if not doctor(root, include_login=False):
        return 1
    login = command_check(
        "Codex 로그인", cfg["codex_command"] + ["login", "status"], root
    )
    if not login.ok:
        print("Codex 로그인 화면을 엽니다. 본인 계정으로 로그인해 주세요.")
        subprocess.run(cfg["codex_command"] + ["login"], cwd=root, check=True)
        login = command_check(
            "Codex 로그인", cfg["codex_command"] + ["login", "status"], root
        )
        if not login.ok:
            raise ValueError("Codex 로그인을 확인하지 못했습니다. " + login.detail)
    identifier = participant(
        args.participant or cfg.get("participant") or answer("배정받은 참가자 번호: ")
    )
    for key, prompt in [
        ("user.name", "Git 제출에 사용할 이름: "),
        ("user.email", "Git 제출에 사용할 이메일: "),
    ]:
        if not git(root, "config", "--get", key, check=False).stdout.strip():
            git(root, "config", "--local", key, answer(prompt))
    print("실습 브랜치:", enroll(root, cfg, identifier))
    from labkit.github_flow import check_submission_ready

    print("제출 준비 확인:", check_submission_ready(root, cfg))
    print("준비 완료. 실행할 실습을 선택하세요.")
    previous = sys.argv
    try:
        sys.argv = [str(root / "lab.py")]
        lab_main()
    finally:
        sys.argv = previous
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="강사용 공통 환경 준비. 모델을 호출하지 않음",
    )
    parser.add_argument("--model")
    parser.add_argument(
        "--reasoning-effort", choices=["minimal", "low", "medium", "high", "xhigh"]
    )
    parser.add_argument("--participant", help="이미 배정받은 참가자 번호")
    parser.add_argument(
        "--check", action="store_true", help="현재 실행·제출 준비 상태만 확인"
    )
    parser.add_argument("--bootstrapped", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.prepare and args.check:
        parser.error("--prepare와 --check 중 하나를 선택하세요.")
    try:
        if not args.bootstrapped:
            python = bootstrap(ROOT)
            original = list(argv) if argv is not None else sys.argv[1:]
            env = {
                **os.environ,
                "PATH": str(python.parent) + os.pathsep + os.environ.get("PATH", ""),
            }
            return subprocess.run(
                [str(python), str(ROOT / "start.py"), "--bootstrapped", *original],
                cwd=ROOT,
                env=env,
            ).returncode
        return launch(ROOT, args)
    except (OSError, ValueError, subprocess.SubprocessError, EOFError) as error:
        print("시작 준비 중 확인이 필요합니다:\n" + str(error), file=sys.stderr)
        print(
            "설정과 실행 기록은 보존했습니다. 이 화면을 연구원에게 보여 주세요.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("시작을 취소했습니다. 시작 파일을 다시 실행하면 이어서 준비합니다.")
        return 130


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise SystemExit(
            "Python 3.10 이상이 필요합니다. 연구원에게 교육용 PC 준비를 요청하세요."
        )
    raise SystemExit(main())
