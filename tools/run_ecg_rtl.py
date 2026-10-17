"""Standalone Phase-2A regression; does not compile or modify the legacy datapath.

Simulator work/VCD/transcripts go under ignored build/phase2a/<run id>.
Summary with exact commands, source hashes and actual statuses goes in docs/.
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
    parser.add_argument("--summary", type=Path, help="New summary file inside this repo; preserves previous phase reports")
    args = parser.parse_args()
    summary_path = args.summary.resolve() if args.summary else ROOT / "docs/phase2a_results.json"
    summary_path.relative_to(ROOT)  # Refuse outputs outside the integration repository.
    if args.summary and summary_path.exists():
        parser.error("--summary must name a new file; existing evidence is preserved")
    build = ROOT / "build/phase2a" / datetime.now().strftime("%Y%m%d_%H%M%S")
    build.mkdir(parents=True, exist_ok=False)
    entries = []

    def run(name, command, required_marker=None, cwd=build):
        print(f"RUN {name}", flush=True)
        try:
            result = subprocess.run([str(c) for c in command], cwd=cwd, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=120)
            output = result.stdout + result.stderr
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            output, code = str(exc), -1
        (build / f"{name}.log").write_text(output, encoding="utf-8", newline="\n")
        ok = code == 0 and not re.search(r"(?:\*\* (?:Error|Fatal):|\bFAIL\b)", output)
        if required_marker:
            ok = ok and required_marker in output
        entry = {"name": name, "status": "PASS" if ok else "FAIL", "exit_code": code,
                 "command": [str(c) for c in command], "cwd": str(cwd),
                 "log": str((build / f"{name}.log").relative_to(ROOT)).replace("\\", "/"),
                 "warning_lines": [line for line in output.splitlines() if "Warning:" in line],
                 "error_lines": [line for line in output.splitlines() if "Error:" in line or "Fatal:" in line or "FAIL" in line],
                 "pass_lines": [line.strip("# ") for line in output.splitlines() if "PASS " in line]}
        entries.append(entry)
        print(f"{entry['status']} {name}", flush=True)
        if not ok:
            print(output[-10000:], flush=True)
        return ok

    run("export_vectors", [sys.executable, "-B", ROOT / "tools/export_ecg_sv_vectors.py"], "PASS:", cwd=ROOT)
    rtl = [ROOT / "rtl/ecg" / f for f in ("ecg_q12_20_pkg.sv", "ecg_model_rom.sv", "ecg_mlp_core.sv")]
    tbs = [ROOT / "tb/ecg" / f for f in ("tb_ecg_arithmetic.sv", "tb_ecg_rom.sv", "tb_ecg_mlp.sv")]
    verilator = shutil.which("verilator") or shutil.which("verilator.exe")
    if verilator:
        run("verilator_version", [verilator, "--version"])
        run("verilator_lint", [verilator, "--lint-only", "--Wall", "--top-module", "ecg_mlp_core", *rtl])
    else:
        entries.append({"name": "verilator_lint", "status": "NOT RUN", "reason": "verilator not found on PATH or audited tool directories"})
    if not shutil.which("iverilog"):
        entries.append({"name": "icarus_simulation", "status": "NOT RUN", "reason": "iverilog/vvp not found; Questa selected"})
    else:
        entries.append({"name": "icarus_simulation", "status": "NOT RUN", "reason": "Questa selected for this regression"})
    exe = lambda name: args.questa_dir / (name + ".exe")
    if not exe("vlog").is_file() or not exe("vsim").is_file():
        entries.append({"name": "questa", "status": "NOT RUN", "reason": f"Questa unavailable at {args.questa_dir}"})
    else:
        run("vlog_version", [exe("vlog"), "-version"])
        run("vsim_version", [exe("vsim"), "-version"])
        initialized = run("vlib", [exe("vlib"), "work"])
        initialized = run("vmap_init", [exe("vmap"), "-c"]) and initialized
        initialized = run("vmap_work", [exe("vmap"), "work", "work"]) and initialized
        compiled = initialized and run("questa_lint_compile", [exe("vlog"), "-sv", "-lint", "-work", "work", *rtl, *tbs])
        if compiled:
            run("core_elaboration", [exe("vopt"), "-work", "work", "work.ecg_mlp_core", "-o", "ecg_core_elab"])
            model = (ROOT / "tests/vectors/model_q12_20.hex").as_posix()
            vec = ROOT / "tests/vectors/phase2a"
            manifest = json.loads((vec / "manifest.json").read_text())
            suites = [
                ("arithmetic", "tb_ecg_arithmetic", None, vec / "arithmetic.mem", manifest["arithmetic_cases"], 0, 0, "PASS arithmetic"),
                ("rom", "tb_ecg_rom", model, None, 0, 0, 0, "PASS ROM"),
                ("golden_protocol", "tb_ecg_mlp", model, vec / "golden.mem", 14, 0, 1, "PASS MLP suite"),
                ("signed_corners", "tb_ecg_mlp", (vec / "corner_model.hex").as_posix(), vec / "corner.mem", 4, 0, 0, "PASS MLP suite"),
            ]
            for f in manifest["failure_suites"]:
                suites.append((f["name"], "tb_ecg_mlp", (vec / (f["name"] + "_model.hex")).as_posix(),
                               vec / (f["name"] + ".mem"), f["cases"], f["error_stage"], 0, "PASS MLP suite"))
            for name, top, rom, vectors, count, error, protocol, marker in suites:
                vcd = (build / f"{name}.vcd").as_posix()
                commands = f"onerror {{quit -code 1}}; vcd file {{{vcd}}}; vcd add -r /{top}/*; run -all; vcd flush; quit -code 0"
                macro = build / f"{name}.do"
                macro.write_text(commands + "\n", encoding="ascii")
                command = [exe("vsim"), "-c", "-onfinish", "stop", "-voptargs=+acc", "-wlf", str(build / f"{name}.wlf")]
                if rom:
                    command.append("-gMODEL_FILE=" + rom)
                command.append("work." + top)
                if vectors:
                    command += ["+VECTORS=" + vectors.as_posix(), f"+CASES={count}", f"+ERROR_STAGE={error}", f"+PROTOCOL={protocol}"]
                command += ["-do", f"do {{{macro.as_posix()}}}"]
                run(name, command, marker)
                wave = Path(vcd)
                entries.append({"name": name + "_vcd", "status": "PASS" if wave.is_file() and wave.stat().st_size > 100 else "FAIL",
                                "file": str(wave.relative_to(ROOT)).replace("\\", "/"), "bytes": wave.stat().st_size if wave.is_file() else 0})
        else:
            entries.append({"name": "simulation", "status": "NOT RUN", "reason": "compile/initialization failed"})
    sources = rtl + tbs + [ROOT / "tools/export_ecg_sv_vectors.py", Path(__file__),
                           ROOT / "tests/vectors/ecg_golden.json", ROOT / "tests/vectors/model_q12_20.hex"]
    summary = {"status": "FAIL" if any(e["status"] == "FAIL" for e in entries) else
               "PASS" if any(e["name"] == "golden_protocol" and e["status"] == "PASS" for e in entries) else "NOT RUN",
               "build_directory": str(build.relative_to(ROOT)).replace("\\", "/"), "checks": entries,
               "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
               "synthesis_timing_resources": {"status": "NOT RUN", "reason": "No Vivado synthesis/place-and-route run in Phase 2A"}}
    with summary_path.open("x" if args.summary else "w", encoding="utf-8") as output:
        output.write(json.dumps(summary, indent=2) + "\n")
    print(f"{summary['status']} Phase 2A; logs and VCD: {build}", flush=True)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
