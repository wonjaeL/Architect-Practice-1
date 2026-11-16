"""Check the local execution path without making a model request."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""


def command_check(name: str, command: list[str], cwd: Path) -> Check:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
        detail = (result.stdout + "\n" + result.stderr).strip()
        return Check(name, result.returncode == 0, detail[-3000:])
    except (OSError, subprocess.TimeoutExpired) as error:
        return Check(name, False, str(error))


def sandbox_check(root: Path, cfg: dict) -> Check:
    prefix = list(cfg["codex_command"])
    if cfg.get("profile"):
        prefix += ["--profile", cfg["profile"]]
    help_result = command_check(
        "샌드박스 명령 확인", prefix + ["sandbox", "--help"], root
    )
    if not help_result.ok:
        return help_result
    with tempfile.TemporaryDirectory(prefix=".lab-preflight-", dir=root) as temporary:
        workspace = Path(temporary)
        # Match the fresh Git root used by a real exercise run.
        initialized = command_check("임시 작업 폴더", ["git", "init", "-q"], workspace)
        if not initialized.ok:
            return initialized
        (workspace / "test_probe.py").write_text(
            "from pathlib import Path\n"
            "def test_workspace_io():\n"
            "    p = Path('probe.txt')\n"
            "    p.write_text('practice1', encoding='utf-8')\n"
            "    assert p.read_text(encoding='utf-8') == 'practice1'\n"
            "    p.unlink()\n",
            encoding="utf-8",
        )
        if "--permission-profile" in help_result.detail:
            command = prefix + ["sandbox", "-P", ":workspace", "-C", str(workspace)]
        elif sys.platform.startswith("linux") and "linux" in help_result.detail:
            command = prefix + ["sandbox", "linux", "--full-auto"]
        elif sys.platform == "darwin" and "macos" in help_result.detail:
            command = prefix + ["sandbox", "macos", "--full-auto"]
        else:
            return Check(
                "샌드박스",
                False,
                "이 Codex CLI의 샌드박스 점검 명령을 지원하지 않습니다. 강사용 준비 안내의 CLI 버전을 확인하세요.",
            )
        probe = (
            "import os, subprocess, sys; "
            "env=dict(os.environ); env.pop('PYTEST_ADDOPTS', None); "
            "env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'; "
            "subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', "
            "'test_probe.py'], env=env, check=True); print('PRACTICE1_SANDBOX_OK')"
        )
        result = command_check(
            "샌드박스 안의 파일 읽기·쓰기와 테스트",
            command + ["--", sys.executable, "-c", probe],
            workspace,
        )
        result.ok = result.ok and "PRACTICE1_SANDBOX_OK" in result.detail
        if not result.ok:
            result.fix = "이 PC의 Codex 샌드박스 설정을 연구원에게 확인하세요."
        return result


def execution_checks(
    root: Path, cfg: dict, *, include_login: bool = True
) -> list[Check]:
    checks = [
        Check(
            "과제 실행 모델",
            bool(cfg.get("model")),
            cfg.get("model")
            or "강사가 start.py --prepare --model 모델명으로 먼저 설정해야 합니다.",
        )
    ]
    tools = [
        command_check(label, command, root)
        for label, command in [
            ("Python 테스트 도구", [sys.executable, "-m", "pytest", "--version"]),
            ("테스트 커버리지", [sys.executable, "-c", "import pytest_cov"]),
            ("린트", [sys.executable, "-m", "ruff", "--version"]),
            ("타입 검사", [sys.executable, "-m", "mypy", "--version"]),
            ("Git", ["git", "--version"]),
            ("Codex", cfg["codex_command"] + ["--version"]),
        ]
    ]
    checks += tools
    if tools[-1].ok:
        if include_login:
            login = command_check(
                "Codex 로그인", cfg["codex_command"] + ["login", "status"], root
            )
            login.fix = "수업 전에 안내된 Codex CLI 로그인을 완료하세요."
            checks.append(login)
        if all(c.ok for c in tools):
            checks.append(sandbox_check(root, cfg))
    return checks


def require_checks(checks: list[Check]) -> None:
    failures = [f"{c.name}: {c.detail}" for c in checks if not c.ok]
    if failures:
        raise ValueError(
            "실습 준비가 완료되지 않았습니다. 모델은 호출하지 않았습니다.\n"
            + "\n".join(failures)
        )
