"""Run actual unittest discovery and save PASS/FAIL/NOT RUN evidence."""
import argparse
import importlib.metadata
import io
import platform
import sys
import unittest
from pathlib import Path

from audit_ecg_model import ROOT, digest, json_bytes


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"test": test.id(), "status": "PASS"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"test": test.id(), "status": "FAIL", "reason": self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"test": test.id(), "status": "FAIL", "reason": self._exc_info_to_string(err, test)})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({"test": test.id(), "status": "NOT RUN", "reason": reason})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs")
    args = parser.parse_args()
    output = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=output, verbosity=2, resultclass=RecordedResult).run(suite)
    versions = {}
    for name in ("numpy", "scipy", "pandas", "scikit-learn", "torch"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "NOT RUN: not installed"
    report = {"status": "PASS" if result.wasSuccessful() else "FAIL", "python": platform.python_version(),
              "command": "python -B tools/run_ecg_tests.py", "discovered": result.testsRun,
              "passed": sum(r["status"] == "PASS" for r in result.records),
              "failed": len(result.failures) + len(result.errors), "not_run": len(result.skipped),
              "versions": versions, "tests": result.records,
              "source_hashes": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p)
                                for folder in (ROOT / "tools", ROOT / "tests") for p in sorted(folder.glob("*.py"))}}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase1a_tests.json").write_bytes(json_bytes(report))
    (args.output_dir / "phase1a_tests.log").write_text(output.getvalue(), encoding="utf-8", newline="\n")
    print(output.getvalue(), end="")
    print(f"{report['status']}: {report['passed']} PASS, {report['failed']} FAIL, {report['not_run']} NOT RUN")
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    sys.exit(main())
