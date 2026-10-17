"""Phase 3A: legacy reproduction, ECG transport checks, and unchanged MLP regression.

No existing summaries/logs/VCD are overwritten. All tool output is retained under
build/phase3a/<unique run>; a new docs/phase3a_results[_run].json indexes each run.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questa-dir", type=Path, default=Path("C:/MentorGraphics/win64"))
    args = parser.parse_args()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "ECG":
        parser.error("Phase 3A runs only on branch ECG")
    build = ROOT / "build/phase3a" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    build.mkdir(parents=True, exist_ok=False)
    checks = []

    def run(name, command, marker=None, expected_baseline=False, cwd=build):
        print("RUN", name, flush=True)
        try:
            proc = subprocess.run([str(c) for c in command], cwd=cwd, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=180)
            output, code = proc.stdout + proc.stderr, proc.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            output, code = str(exc), -1
        logfile = build / f"{name}.log"
        logfile.write_text(output, encoding="utf-8", newline="\n")
        passed = code == 0 and not re.search(r"\*\* (?:Error|Fatal)|\bFAIL\b", output)
        if marker:
            passed = passed and marker in output
        # Questa can return 0 after a stopped $fatal followed by macro quit.
        # Treat the exact fatal assertion as FAIL regardless of process status.
        reproduced = expected_baseline and "FAIL LEGACY_CONTIGUOUS expected=3 actual=1" in output
        check = {"name": name, "status": "PASS" if passed else "FAIL", "exit_code": code,
                 "command": [str(c) for c in command], "cwd": str(cwd),
                 "log": logfile.relative_to(ROOT).as_posix(), "expected_baseline_failure": bool(reproduced),
                 "warnings": [s for s in output.splitlines() if "Warning:" in s],
                 "errors": [s for s in output.splitlines() if "Error" in s or "Fatal" in s or "FAIL" in s],
                 "pass_lines": [s.strip("# ") for s in output.splitlines() if "PASS " in s]}
        checks.append(check)
        print(check["status"], name, "(baseline reproduced)" if reproduced else "", flush=True)
        if not passed and not reproduced:
            print(output[-10000:], flush=True)
        return passed or reproduced

    def simulate(name, top, parameter=None, expected_baseline=False):
        vcd = build / f"{name}.vcd"
        macro = build / f"{name}.do"
        # Do not dump the TB's 65536-bit coverage bitmap: only interface and DUT.
        if top == "tb_ecg_sample_interface":
            scope = "pulse_source" if parameter == 1 else "replay_source"
            signals = " ".join(f"/{top}/{s}" for s in (
                "clk", "rst_n", "input_sample", "input_valid", "input_ready",
                "output_ready", "output_sample", "output_valid", "upstream_loss",
                "overflow_pulse", "overflow_flag"))
            dump = f"vcd add {signals}; vcd add -r /{top}/{scope}/dut/*"
        else:
            dump = f"vcd add -r /{top}/*"
        macro.write_text(f"onerror {{quit -code 1}}; "
                         f"vcd file {{{vcd.as_posix()}}}; {dump}; run -all; vcd flush; quit -code 0\n", encoding="ascii")
        command = [exe("vsim"), "-c", "-onfinish", "stop", "-voptargs=+acc", "-wlf", build / f"{name}.wlf"]
        if parameter is not None:
            command.append(f"-gPULSE_MODE={parameter}")
        command += ["work." + top, "-do", f"do {{{macro.as_posix()}}}"]
        ok = run(name, command, "PASS ECG_SAMPLE" if not expected_baseline else None, expected_baseline)
        wave_ok = vcd.is_file() and vcd.stat().st_size > 100
        checks.append({"name": name + "_vcd", "status": "PASS" if wave_ok else "FAIL",
                       "file": vcd.relative_to(ROOT).as_posix(), "bytes": vcd.stat().st_size if wave_ok else 0})
        return ok and wave_ok

    rtl = [ROOT / "rtl/ecg" / n for n in ("ecg_sample_interface.sv", "ecg_sample_pulse_adapter.sv")]
    testbench = ROOT / "tb/ecg/tb_ecg_sample_interface.sv"
    legacy = [ROOT / "adc/adc_interface.v", ROOT / "tb/ecg/tb_legacy_adc_contiguous.sv"]
    sources = rtl + [testbench, *legacy, Path(__file__), ROOT / "tools/run_ecg_rtl.py"]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    exe = lambda name: args.questa_dir / (name + ".exe")
    verilator = shutil.which("verilator") or shutil.which("verilator.exe")
    if verilator:
        run("verilator_version", [verilator, "--version"])
        for top in ("ecg_sample_interface", "ecg_sample_pulse_adapter"):
            run("verilator_" + top, [verilator, "--lint-only", "--Wall", "--top-module", top, *rtl])
    else:
        checks.append({"name": "verilator_lint", "status": "NOT RUN", "reason": "Not found on PATH or inspected C:/msys64/C:/MentorGraphics tool roots; not installed"})
    sample_ok = False
    if all(exe(n).is_file() for n in ("vlog", "vsim", "vlib", "vmap", "vopt")):
        run("questa_version", [exe("vlog"), "-version"])
        initialized = run("vlib", [exe("vlib"), "work"])
        initialized = run("vmap_init", [exe("vmap"), "-c"]) and initialized
        initialized = run("vmap_work", [exe("vmap"), "work", "work"]) and initialized
        compiled = initialized and run("sample_lint_compile", [exe("vlog"), "-sv", "-lint", *rtl, testbench])
        legacy_compiled = initialized and run("legacy_compile", [exe("vlog"), "-sv", "-lint", *legacy])
        if legacy_compiled:
            simulate("legacy_contiguous", "tb_legacy_adc_contiguous", expected_baseline=True)
        if compiled:
            elaborated = run("core_elaboration", [exe("vopt"), "work.ecg_sample_interface", "-o", "ecg_sample_elab"])
            elaborated = run("adapter_elaboration", [exe("vopt"), "work.ecg_sample_pulse_adapter", "-o", "ecg_pulse_elab"]) and elaborated
            if elaborated:
                replay = simulate("replay_ready_valid", "tb_ecg_sample_interface", 0)
                pulse = simulate("pulse_overflow", "tb_ecg_sample_interface", 1)
                sample_ok = replay and pulse
    else:
        checks.append({"name": "questa_simulation", "status": "NOT RUN", "reason": f"Questa unavailable at {args.questa_dir}"})

    # One complete MLP regression only after the new transport suite passes.
    mlp_summary = build / "mlp_results.json"
    if sample_ok:
        ok = run("phase2a_mlp_regression", [sys.executable, "-B", ROOT / "tools/run_ecg_rtl.py",
                 "--questa-dir", args.questa_dir, "--summary", mlp_summary], "PASS Phase 2A", cwd=ROOT)
        if ok:
            mlp = json.loads(mlp_summary.read_text())
            if mlp["status"] != "PASS":
                checks.append({"name": "mlp_summary", "status": "FAIL"})
    else:
        checks.append({"name": "phase2a_mlp_regression", "status": "NOT RUN", "reason": "Transport simulation has not passed; fix before MLP regression"})
    same = all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    checks.append({"name": "sources_unchanged_during_run", "status": "PASS" if same else "FAIL"})
    failed = any(c["status"] == "FAIL" and not c.get("expected_baseline_failure", False) for c in checks)
    summary = {"status": "FAIL" if failed else "PASS" if sample_ok else "NOT RUN", "checks": checks,
               "build_directory": build.relative_to(ROOT).as_posix(), "branch": branch,
               "source_sha256": hashes, "mlp_summary": mlp_summary.relative_to(ROOT).as_posix() if mlp_summary.exists() else None,
               "hardware_synthesis_timing": "NOT RUN"}
    encoded = json.dumps(summary, indent=2) + "\n"
    (build / "results.json").write_text(encoded, encoding="utf-8")
    path = ROOT / "docs/phase3a_results.json"
    if path.exists():
        path = ROOT / "docs" / f"phase3a_results_{build.name}.json"
    with path.open("x", encoding="utf-8") as output:
        output.write(encoded)
    print(summary["status"], "Phase 3A:", build, flush=True)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
