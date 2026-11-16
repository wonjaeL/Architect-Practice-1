"""Runs inside the disposable, offline grading container; no credentials."""

import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def main():
    os.environ["PYTHONPATH"] = "/work/src"
    suites = {}
    for name in ("tests", "submitted_tests"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--import-mode=importlib",
                "--junitxml=/tmp/" + name + ".xml",
                name,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        xml = Path("/tmp/" + name + ".xml")
        count = (
            sum(int(s.get("tests", 0)) for s in ET.parse(xml).iter("testsuite"))
            if xml.exists()
            else 0
        )
        suites[name] = {"passed": result.returncode == 0 and count > 0, "tests": count}
        if result.returncode:
            print(result.stdout[-6000:], file=sys.stderr)
            print(result.stderr[-2000:], file=sys.stderr)
    policy = subprocess.run(
        [
            sys.executable,
            "/grader/coupon_checks.py",
            "/work",
            "--output",
            "/tmp/policy.json",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    report = json.loads(Path("/tmp/policy.json").read_text())
    suites["policy"] = {
        "passed": policy.returncode == 0,
        "tests": report["total"],
        "passed_count": report["passed"],
        "failures": [c["name"] for c in report["checks"] if not c["passed"]],
    }
    print(json.dumps(suites))


if __name__ == "__main__":
    main()
