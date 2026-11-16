"""Collect public student branches, grade in Docker, write receipts and a static board."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from labkit.common import digest, extract_zip, read_json, source_digest, write_json
from labkit.report import eligible

ROOT = Path(__file__).resolve().parents[1]
GRADER = (
    "practice1-policy-v1-"
    + hashlib.sha256(
        b"".join(
            (ROOT / "grading" / name).read_bytes()
            for name in (
                "collect.py",
                "check_submission.py",
                "coupon_checks.py",
                "Dockerfile",
            )
        )
    ).hexdigest()[:12]
)
SAFE_ID = re.compile(r"[a-zA-Z0-9_-]{1,80}\Z")


def api(path: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "practice1-grader",
    }
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    request = urllib.request.Request("https://api.github.com/" + path, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def git(*args: str, binary=False):
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=not binary, timeout=120
    )


def submissions(repository: str):
    refs = []
    page = 1
    while True:
        batch = api(f"repos/{repository}/branches?per_page=100&page={page}")
        refs.extend(b for b in batch if b["name"].startswith("students/"))
        if len(batch) < 100:
            break
        page += 1
    for branch in sorted(refs, key=lambda b: b["name"]):
        participant = branch["name"].removeprefix("students/")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", participant):
            continue
        commit = branch["commit"]["sha"]
        git("fetch", "--quiet", "origin", commit)
        for line in git("ls-tree", "-r", commit, "--", "submissions/").splitlines():
            metadata, path = line.split("\t", 1)
            mode, kind, blob = metadata.split()
            run_id = Path(path).stem
            if (
                mode != "100644"
                or kind != "blob"
                or path != f"submissions/{run_id}.zip"
                or not SAFE_ID.fullmatch(run_id)
            ):
                continue
            if int(git("cat-file", "-s", blob)) > 15_000_000:
                continue
            yield participant, run_id, blob, git("cat-file", "blob", blob, binary=True)


def grade(participant: str, run_id: str, blob: str, raw: bytes) -> dict:
    receipt = {
        "run_id": run_id,
        "participant": participant,
        "artifact_blob": blob,
        "grader": GRADER,
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
    }
    public = {"id": run_id, "participant": participant, "grade": receipt}
    try:
        with tempfile.TemporaryDirectory(prefix="practice1-grade-") as temporary:
            directory = Path(temporary)
            archive, workspace = directory / "archive", directory / "workspace"
            extract_zip(raw, archive)
            summary = read_json(archive / "summary.json")
            if summary["id"] != run_id or summary["participant"] != participant:
                raise ValueError("제출 경로와 참가자·실행 번호가 다릅니다.")
            receipt["source_sha256"] = source_digest(archive / "workspace")
            if receipt["source_sha256"] != summary["source_sha256"]:
                raise ValueError("제출 소스 체크섬이 일치하지 않습니다.")
            conditions = summary["conditions"]
            for key, path in [
                ("baseline_sha256", "assets/parkfee.zip"),
                ("request_sha256", "task/request.md"),
                ("test_helper_sha256", "labkit/test_summary.py"),
            ]:
                if conditions.get(key) != digest(ROOT / path):
                    raise ValueError("배포된 과제와 제출의 실행 조건이 다릅니다.")
            condition_id = hashlib.sha256(
                json.dumps(conditions, sort_keys=True).encode()
            ).hexdigest()
            if summary.get("condition_id") != condition_id:
                raise ValueError("실행 조건 체크섬이 일치하지 않습니다.")
            public.update(
                {
                    k: summary.get(k)
                    for k in (
                        "variant",
                        "label",
                        "conditions",
                        "condition_id",
                        "execution_status",
                        "comparison_valid",
                        "techniques",
                        "note",
                    )
                }
            )
            # Publish only aggregate counters, never model logs or commands.
            usage = summary.get("usage", {})
            public["usage"] = {
                k: usage.get(k)
                for k in ("input_tokens", "cached_input_tokens", "output_tokens")
            }
            extract_zip((ROOT / "assets/parkfee.zip").read_bytes(), workspace)
            submitted_tests = archive / "workspace/tests"
            changed_tests = any(
                not (workspace / "tests" / p.relative_to(submitted_tests)).exists()
                or p.read_bytes()
                != (workspace / "tests" / p.relative_to(submitted_tests)).read_bytes()
                for p in submitted_tests.rglob("*.py")
            )
            if not changed_tests:
                receipt.update(
                    status="failed", message="쿠폰 관련 테스트를 추가해야 합니다."
                )
                return public
            shutil.rmtree(workspace / "src")
            shutil.copytree(archive / "workspace/src", workspace / "src")
            shutil.copytree(submitted_tests, workspace / "submitted_tests")
            directory.chmod(0o755)
            # No credential, Docker socket, network or writable source mount is exposed.
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--read-only",
                    "--pids-limit=128",
                    "--memory=512m",
                    "--cpus=2",
                    "--tmpfs=/tmp:rw,nosuid,size=128m",
                    "-v",
                    f"{workspace}:/work:ro",
                    "-v",
                    f"{ROOT / 'grading'}:/grader:ro",
                    "practice1-grader",
                    "python",
                    "/grader/check_submission.py",
                ],
                capture_output=True,
                text=True,
                timeout=420,
            )
            if result.returncode:
                raise ValueError("채점 실행 오류: " + result.stderr[-1000:])
            suites = json.loads(result.stdout.strip())
            receipt.update(
                status="passed"
                if all(s["passed"] for s in suites.values())
                else "failed",
                checks=suites,
            )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        subprocess.SubprocessError,
    ) as error:
        receipt["message"] = str(error)[:1200]
    return public


def render(records: list[dict], output: Path) -> None:
    records.sort(key=lambda r: (r["participant"], r["id"]))
    write_json(output / "data.json", records)
    write_json(
        output / "service.json",
        {
            "schema": 1,
            "grader": GRADER,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    rows = []

    def esc(value):
        return html.escape(str(value))

    for run in records:
        grade = run["grade"]
        baseline = next(
            (
                r
                for r in records
                if r["participant"] == run["participant"]
                and r.get("variant") == "baseline"
                and eligible(r)
                and r.get("condition_id") == run.get("condition_id")
            ),
            None,
        )
        reduction = "—"
        if eligible(run) and baseline and baseline["usage"]["input_tokens"] > 0:
            reduction = f"{(1 - run['usage']['input_tokens'] / baseline['usage']['input_tokens']) * 100:.1f}%"
        status = {"passed": "통과", "failed": "실패", "error": "채점 오류"}.get(
            grade["status"], "대기"
        )
        path = f"grades/{run['participant']}/{run['id']}.json"
        cells = [
            run["participant"],
            run.get("label", "—"),
            run.get("usage", {}).get("input_tokens"),
            status,
            reduction,
            ", ".join(run.get("techniques") or []),
            run.get("note") or "",
        ]
        rows.append(
            '<tr data-run="'
            + esc(run["id"])
            + '">'
            + "".join("<td>" + esc(v) + "</td>" for v in cells)
            + f'<td><a href="{esc(path)}">채점 상세</a></td></tr>'
        )
    updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    page = (
        """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30">
<title>실습 1 전체 결과</title><style>body{font:16px/1.6 system-ui;max-width:1400px;margin:40px auto;padding:0 20px;color:#202329}table{border-collapse:collapse;width:100%}th,td{padding:12px;border-bottom:1px solid #ddd;text-align:left}a{color:#305bcc}.muted{color:#666}</style>
<h1>실습 1 전체 결과</h1><p>참가자별 실행 순서로 표시합니다. 순위를 매기지 않습니다.</p>
<p>절감률은 같은 참가자·실행 조건에서 채점에 통과한 첫 기본 지침 실행과 비교합니다. 캐시 입력은 입력 총량에 이미 포함됩니다.</p>
<p class="muted">30초마다 새로고침 · 갱신: """
        + esc(updated)
        + """</p>
<p><a href="data.json">집계 데이터</a></p><div style="overflow:auto"><table><thead><tr>
<th>참가자</th><th>지침</th><th>입력 토큰</th><th>채점</th><th>기본 대비 절감</th><th>기법</th><th>메모</th><th>상세</th>
</tr></thead><tbody>"""
        + (
            "\n".join(rows)
            or '<tr><td colspan="8">아직 제출된 실행이 없습니다.</td></tr>'
        )
        + "</tbody></table></div></html>"
    )
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / ".nojekyll").touch()
    (output / "README.md").write_text(
        f"# 실습 1 결과\n\n갱신: {updated}\n\n제출 {len(records)}건. `index.html` 또는 GitHub Pages에서 확인합니다.\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    old = {}
    if args.previous and (args.previous / "data.json").exists():
        old = {
            (r["participant"], r["id"], r["grade"]["artifact_blob"]): r
            for r in json.loads((args.previous / "data.json").read_text())
            if r["grade"].get("grader") == GRADER
            and r["grade"].get("status") in ("passed", "failed")
        }
    records = []
    for participant, run_id, blob, raw in submissions(args.repository):
        record = old.get((participant, run_id, blob)) or grade(
            participant, run_id, blob, raw
        )
        records.append(record)
        write_json(
            args.output / "grades" / participant / (run_id + ".json"), record["grade"]
        )
        print(participant, run_id, record["grade"]["status"], flush=True)
    render(records, args.output)


if __name__ == "__main__":
    main()
