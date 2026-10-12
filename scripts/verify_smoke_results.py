#!/usr/bin/env python3
"""Fail closed on a crashed/timed out/skipped/empty instrumentation run; save a small summary."""
import argparse
import json
import re
from pathlib import Path

EXPECTED = {
    "MediaControllerSmokeTest": 5,
    "VoiceOwnershipSmokeTest": 1,
    "PickerContractSmokeTest": 3,
    "SystemPickerSmokeTest": 1,
}


def verify_results(text):
    if not re.search(r"^INSTRUMENTATION_CODE: -1\s*$", text, re.M):
        raise ValueError("Instrumentation did not finish successfully")
    if not re.search(r"\bOK \(10 tests\)", text):
        raise ValueError("Expected all ten smoke tests")
    observed = {}
    completed = []
    status = {}
    for line in text.splitlines():
        item = re.match(r"INSTRUMENTATION_STATUS: (class|test)=(.*)", line)
        if item:
            status[item[1]] = item[2]
        code = re.fullmatch(r"INSTRUMENTATION_STATUS_CODE: (-?\d+)", line)
        if code:
            value = int(code[1])
            if value not in (0, 1):
                raise ValueError("Failed, ignored or incomplete instrumentation test")
            if value == 0:
                cls = status.get("class", "").rsplit(".", 1)[-1]
                name = status.get("test", "")
                if not name or cls not in EXPECTED or (cls, name) in completed:
                    raise ValueError("Unexpected/duplicate instrumentation test")
                completed.append((cls, name))
                observed[cls] = observed.get(cls, 0) + 1
            status = {}
    if observed != EXPECTED:
        raise ValueError(f"Incomplete test classes: {observed}")
    return {"status": "passed", "test_count": len(completed),
            "tests": [f"{cls}.{name}" for cls, name in completed],
            "limits": ["Injected result URI tests are not actual system picker selection",
                       "Compose state restore is not full process death",
                       "No real-account login, upload or production screen validation"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = verify_results(args.input.read_text())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("All ten offline smoke tests passed.")


if __name__ == "__main__":
    main()
