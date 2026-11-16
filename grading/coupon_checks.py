"""Coupon acceptance checks derived from the supplied operating policy."""

from __future__ import annotations
import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    cases = []

    def case(
        name,
        *,
        minutes=120,
        lot="HJ-02",
        coupon=None,
        total=6000,
        status=None,
        entry="2026-09-05T09:00:00",
        exit_at=None,
        plate="12가3456",
        extra=(),
        error=None,
        text=False,
    ):
        exit_at = (
            exit_at
            or (datetime.fromisoformat(entry) + timedelta(minutes=minutes)).isoformat()
        )
        cases.append(
            dict(
                name=name,
                lot=lot,
                coupon=coupon,
                total=total,
                status=status,
                entry=entry,
                exit_at=exit_at,
                plate=plate,
                extra=extra,
                error=error,
                text=text,
            )
        )

    case("no coupon JSON field is null")
    case("unknown coupon E2001", coupon="REHEARSAL-MISSING", error="E2001")
    case("time coupon", coupon="HJM-2609-0001", total=3000, status="applied")
    case(
        "time subtraction before daily cap",
        minutes=660,
        coupon="HJM-2609-0002",
        total=27000,
        status="applied",
    )
    case(
        "amount subtraction after daily cap",
        minutes=660,
        coupon="HJM-2609-0003",
        total=29000,
        status="applied",
    )
    case(
        "amount cannot make payment negative",
        minutes=16,
        coupon="HJM-2609-0004",
        total=0,
        status="applied",
    )
    case(
        "do not stack coupon and discounts",
        coupon="HJM-2609-0003",
        extra=("--vehicle-type", "compact", "--member"),
        total=3700,
        status="unused",
    )
    case(
        "coupon beats membership",
        coupon="HJM-2609-0001",
        extra=("--member",),
        total=3000,
        status="applied",
    )
    case(
        "exact tie returns coupon",
        coupon="REHEARSAL-AMOUNT-600",
        extra=("--member",),
        total=5400,
        status="unused",
    )
    case(
        "compare after rounding",
        coupon="REHEARSAL-AMOUNT-2250",
        extra=("--vehicle-type", "compact", "--member"),
        total=3700,
        status="unused",
    )
    case(
        "grace at boundary returns coupon",
        minutes=15,
        coupon="HJM-2609-0001",
        total=0,
        status="unused",
    )
    case(
        "above grace can apply coupon",
        minutes=16,
        coupon="HJM-2609-0001",
        total=0,
        status="applied",
    )
    case(
        "do not reapply grace after time deduction",
        minutes=60,
        coupon="REHEARSAL-TIME-50",
        total=1500,
        status="applied",
    )
    case(
        "wrong parking lot returns coupon",
        lot="HJ-01",
        coupon="HJM-2609-0001",
        total=6500,
        status="unused",
    )
    case(
        "expiry checked at exit",
        entry="2026-09-10T22:00:00",
        exit_at="2026-09-11T01:00:00",
        coupon="HJM-2609-0004",
        total=9000,
        status="expired",
    )
    case(
        "before validity start",
        lot="HJ-01",
        entry="2026-09-15T07:00:00",
        minutes=60,
        coupon="HJT-2609-0002",
        total=3500,
        status="unused",
    )
    case(
        "validity start is inclusive",
        lot="HJ-01",
        entry="2026-09-15T08:00:00",
        minutes=60,
        coupon="HJT-2609-0002",
        total=1500,
        status="applied",
    )
    case(
        "validity end is inclusive",
        lot="HJ-01",
        entry="2026-09-15T17:00:00",
        minutes=60,
        coupon="HJT-2609-0002",
        total=1500,
        status="applied",
    )
    case(
        "one second after validity end",
        lot="HJ-01",
        entry="2026-09-15T17:00:00",
        exit_at="2026-09-15T18:00:01",
        coupon="HJT-2609-0002",
        total=4000,
        status="expired",
    )
    case(
        "season pass returns coupon",
        lot="HJ-01",
        plate="34나5678",
        coupon="HJT-2609-0001",
        total=0,
        status="unused",
    )
    case(
        "time coupon across daily boundary",
        minutes=1441,
        coupon="HJM-2609-0002",
        total=30000,
        status="applied",
    )
    case(
        "parking time rounds seconds up",
        exit_at="2026-09-05T09:15:01",
        coupon="HJM-2609-0001",
        total=0,
        status="applied",
    )
    case("text receipt applied", coupon="HJM-2609-0001", status="applied", text=True)
    case("text receipt expired", coupon="HJM-2608-0107", status="expired", text=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="practice1-acceptance-") as temporary:
        data = Path(temporary) / "data"
        shutil.copytree(workspace / "data", data)
        coupons = json.loads((data / "coupons.json").read_text())
        template = next(c for c in coupons if c["code"] == "HJM-2609-0003")
        for code, kind, value in [
            ("REHEARSAL-AMOUNT-600", "amount", 600),
            ("REHEARSAL-AMOUNT-2250", "amount", 2250),
            ("REHEARSAL-TIME-50", "time", 50),
        ]:
            coupons.append({**template, "code": code, "kind": kind, "value": value})
        (data / "coupons.json").write_text(json.dumps(coupons, ensure_ascii=False))
        env = {
            **os.environ,
            "PYTHONPATH": str(workspace / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for c in cases:
            command = [
                sys.executable,
                "-m",
                "parkfee",
                "--data-dir",
                str(data),
                "calc",
                "--lot",
                c["lot"],
                "--plate",
                c["plate"],
                "--entry",
                c["entry"],
                "--exit",
                c["exit_at"],
                "--format",
                "text" if c["text"] else "json",
                *c["extra"],
            ]
            if c["coupon"]:
                command += ["--coupon", c["coupon"]]
            p = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            ok = False
            reason = ""
            try:
                if c["error"]:
                    assert p.returncode == 3 and c["error"] in p.stderr, (
                        "expected exit 3 and E2001"
                    )
                else:
                    assert p.returncode == 0, (
                        f"exit {p.returncode}: {p.stderr.strip()[-300:]}"
                    )
                    if c["text"]:
                        assert c["coupon"] in p.stdout, (
                            "coupon code missing in text receipt"
                        )
                        marker = {
                            "applied": "사용",
                            "expired": "만료",
                            "unused": "반환",
                        }[c["status"]]
                        assert marker in p.stdout or c["status"] in p.stdout, (
                            "coupon status missing in text receipt"
                        )
                    else:
                        payload = json.loads(p.stdout)
                        assert payload["total"] == c["total"], (
                            f"total {payload['total']} != {c['total']}"
                        )
                        expected = (
                            {"code": c["coupon"], "status": c["status"]}
                            if c["coupon"]
                            else None
                        )
                        assert "coupon" in payload and payload["coupon"] == expected, (
                            f"coupon {payload.get('coupon', 'MISSING')} != {expected}"
                        )
                        assert (
                            payload["vat"]["supply"] + payload["vat"]["tax"]
                            == payload["total"]
                        ), "VAT total mismatch"
                ok = True
            except (AssertionError, KeyError, ValueError) as error:
                reason = str(error)
            results.append({"name": c["name"], "passed": ok, "reason": reason})
    result = {
        "grader": "practice1-policy-v1",
        "workspace": str(workspace),
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "checks": results,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "checks"},
            ensure_ascii=False,
            indent=2,
        )
    )
    for r in results:
        if not r["passed"]:
            print("FAIL", r["name"], ":", r["reason"])
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
