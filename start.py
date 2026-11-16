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
    from labkit.github_flow import enroll, participant
    from labkit.runner import config, doctor, initialize, run_menu

    cfg = config(root)
    if args.participant:
        cfg["participant"] = participant(args.participant)
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
        ok = doctor(root, submission=False, include_login=False)
        if ok:
            print(
                "공통 환경 준비 완료. 개인 PC에서 python start.py doctor로 확인하세요."
            )
        return 0 if ok else 1
    if args.action == "doctor" or args.check:
        return 0 if doctor(root, cfg=cfg) else 1
    if not doctor(root, cfg=cfg):
        return 1
    identifier = participant(cfg.get("participant") or answer("배정받은 참가자 번호: "))
    print("실습 브랜치:", enroll(root, cfg, identifier))
    initialize(root)
    run_menu(root, ready_config=cfg)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", choices=["doctor"], help="실습 준비 상태 확인"
    )
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
    parser.add_argument("--check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--bootstrapped", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.prepare and (args.check or args.action):
        parser.error("--prepare와 doctor 중 하나를 선택하세요.")
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
