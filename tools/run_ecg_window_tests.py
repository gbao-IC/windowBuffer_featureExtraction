"""Phase 3B standalone window and Phase3A+Phase2A regression, preserving old evidence."""
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
        parser.error("Run Phase3B only on ECG")
    build = ROOT / "build/phase3b" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    build.mkdir(parents=True, exist_ok=False)
    checks = []
    exe = lambda n: args.questa_dir / (n + ".exe")
    rtl = [ROOT / "rtl/ecg" / n for n in ("ecg_sample_interface.sv", "ecg_sample_pulse_adapter.sv", "ecg_window_buffer.sv")]
    tbs = [ROOT / "tb/ecg" / n for n in ("tb_ecg_window_buffer.sv", "tb_legacy_window_last.sv")]
    sources = rtl + tbs + [ROOT / "window/window_buffer.v", Path(__file__), ROOT / "tools/run_ecg_sample_tests.py", ROOT / "tools/run_ecg_rtl.py"]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}

    def run(name, command, marker=None, baseline=False, composite=False, cwd=build, timeout=180):
        print("RUN", name, flush=True)
        try:
            p = subprocess.run([str(c) for c in command], cwd=cwd, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout)
            output, code = p.stdout + p.stderr, p.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            output, code = str(exc), -1
        (build / f"{name}.log").write_text(output, encoding="utf-8", newline="\n")
        diagnostic = bool(re.search(r"\*\* (?:Error|Fatal)|\bFAIL\b", output))
        ok = code == 0 and (not diagnostic or composite) and (not marker or marker in output)
        reproduced = baseline and "FAIL LEGACY_WINDOW_LAST" in output and "count511" in output
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "exit_code": code,
                       "expected_baseline_failure": reproduced, "command": [str(c) for c in command], "cwd": str(cwd),
                       "log": (build / f"{name}.log").relative_to(ROOT).as_posix(),
                       "warnings": [s for s in output.splitlines() if "Warning:" in s],
                       "errors": [s for s in output.splitlines() if "Error" in s or "Fatal" in s or "FAIL" in s],
                       "pass_lines": [s.strip("# ") for s in output.splitlines() if "PASS " in s]})
        print(checks[-1]["status"], name, "(baseline reproduced)" if reproduced else "", flush=True)
        if not ok and not reproduced:
            print(output[-10000:], flush=True)
        return ok or reproduced

    def simulate(name, n=347, link=0, baseline=False):
        top = "tb_legacy_window_last" if baseline else "tb_ecg_window_buffer"
        wave = build / f"{name}.vcd"
        macro = build / f"{name}.do"
        if baseline:
            dump = f"vcd add -r /{top}/*"
        else:
            # Interface + DUT control/data, not queues/large RAM/scoreboard arrays.
            ports = "clk rst_n flush source_loss start_valid start_ready tag beat rr prev_rr src_valid src_ready src_data sample_valid sample_ready sample_data frame_valid out_tag out_beat out_rr out_prev_rr collected release_valid release_ready req_valid req_ready req_addr rsp_valid rsp_ready rsp_data rsp_addr rsp_error fault loss_flag frame_abort adapter_loss adapter_sticky"
            dump = "vcd add " + " ".join(f"/{top}/{s}" for s in ports.split())
            dump += f"; vcd add /{top}/dut/state /{top}/dut/write_fire /{top}/dut/read_fire /{top}/dut/response_pending"
        macro.write_text(f"onerror {{quit -code 1}}; vcd file {{{wave.as_posix()}}}; {dump}; run -all; vcd flush; quit -code 0\n", encoding="ascii")
        cmd = [exe("vsim"), "-c", "-onfinish", "stop", "-voptargs=+acc", "-wlf", build / f"{name}.wlf"]
        if not baseline:
            cmd += [f"-gN={n}", f"-gLINK_MODE={link}"]
        cmd += ["work." + top, "-do", f"do {{{macro.as_posix()}}}"]
        ok = run(name, cmd, None if baseline else "PASS ECG_WINDOW", baseline)
        exists = wave.is_file() and wave.stat().st_size > 100
        checks.append({"name": name + "_vcd", "status": "PASS" if exists else "FAIL",
                       "file": wave.relative_to(ROOT).as_posix(), "bytes": wave.stat().st_size if exists else 0})
        return ok and exists

    verilator = shutil.which("verilator") or shutil.which("verilator.exe")
    if verilator:
        run("verilator_version", [verilator, "--version"])
        run("verilator_window_lint", [verilator, "--lint-only", "--Wall", "--top-module", "ecg_window_buffer", rtl[-1]])
    else:
        checks.append({"name": "verilator_lint", "status": "NOT RUN", "reason": "Executable unavailable on PATH; no installation performed"})
    passed = False
    if all(exe(n).is_file() for n in ("vlog", "vopt", "vsim", "vlib", "vmap")):
        run("questa_version", [exe("vlog"), "-version"])
        initialized = run("vlib", [exe("vlib"), "work"])
        initialized = run("vmap_init", [exe("vmap"), "-c"]) and initialized
        initialized = run("vmap_work", [exe("vmap"), "work", "work"]) and initialized
        compiled = initialized and run("window_lint_compile", [exe("vlog"), "-sv", "-lint", *rtl, tbs[0]])
        if initialized and run("legacy_compile", [exe("vlog"), "-sv", "-lint", ROOT / "window/window_buffer.v", tbs[1]]):
            simulate("legacy_last_sample", baseline=True)
        if compiled and run("window_elaboration", [exe("vopt"), "work.ecg_window_buffer", "-o", "ecg_window_elab"]):
            outcomes = []
            for name, n, link in (("window347",347,0), ("window500",500,0), ("window1",1,0),
                                  ("replay_window347",347,1), ("pulse_window347",347,2)):
                outcomes.append(simulate(name, n, link))
            passed = all(outcomes)
    else:
        checks.append({"name": "questa", "status": "NOT RUN", "reason": f"Questa unavailable at {args.questa_dir}"})

    nested = None
    if passed:
        before = set((ROOT / "build/phase3a").glob("*/results.json"))
        # Child logs legitimately include the known legacy ADC FAIL. Validate its
        # structured result and every unexpected failure, not just its PASS marker.
        ok = run("sample_and_mlp_regression", [sys.executable, "-B", ROOT / "tools/run_ecg_sample_tests.py", "--questa-dir", args.questa_dir],
                 "PASS Phase 3A:", composite=True, cwd=ROOT, timeout=1200)
        after = set((ROOT / "build/phase3a").glob("*/results.json")) - before
        if ok and len(after) == 1:
            path = after.pop()
            data = json.loads(path.read_text())
            nested = path.relative_to(ROOT).as_posix()
            ok = data["status"] == "PASS" and not any(c["status"] == "FAIL" and not c.get("expected_baseline_failure") for c in data["checks"])
            mlp = json.loads((ROOT / data["mlp_summary"]).read_text())
            ok = ok and mlp["status"] == "PASS"
        else:
            ok = False
        checks.append({"name": "nested_regression_results", "status": "PASS" if ok else "FAIL"})
    else:
        checks.append({"name": "sample_and_mlp_regression", "status": "NOT RUN", "reason": "Run after window checks pass"})
    same = all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    checks.append({"name": "tested_sources_unchanged", "status": "PASS" if same else "FAIL"})
    failed = any(c["status"] == "FAIL" and not c.get("expected_baseline_failure") for c in checks)
    result = {"status": "FAIL" if failed else "PASS" if passed else "NOT RUN", "checks": checks,
              "source_sha256": hashes, "build_directory": build.relative_to(ROOT).as_posix(),
              "sample_regression_results": nested, "hardware_timing_resources": "NOT RUN", "real_ecg_preprocessing_parity": "NOT RUN"}
    encoded = json.dumps(result, indent=2) + "\n"
    (build / "results.json").write_text(encoded, encoding="utf-8")
    summary = ROOT / "docs/phase3b_results.json"
    if summary.exists(): summary = ROOT / "docs" / f"phase3b_results_{build.name}.json"
    with summary.open("x", encoding="utf-8") as out: out.write(encoded)
    print(result["status"], "Phase 3B:", build, flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
