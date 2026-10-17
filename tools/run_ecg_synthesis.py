"""Stage immutable ECG sources and run Vivado OOC analysis without installing tools.

Exit 0: requested Vivado commands completed (NOT timing signoff).
Exit 1: preflight or tool failure. Exit 2: Vivado unavailable / hardware NOT RUN.
Exact commands, hashes, logs and raw reports remain in a unique build directory.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODEL = "tests/vectors/model_q12_20.hex"
MODEL_SHA = "44b77346ac8d1636c2ccd30e2dce936e993560bfb2d37d4aa4d4e6250a847f41"
INPUTS = ["rtl/ecg/" + n for n in
          ("ecg_q12_20_pkg.sv", "ecg_model_rom.sv", "ecg_mlp_core.sv")] + [
    MODEL, "synthesis/ecg/ecg_mlp_ooc.xdc", "synthesis/ecg/run_vivado.tcl"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_model(data):
    words = data.decode("ascii").split()
    if len(words) != 164 or any(not re.fullmatch(r"[0-9a-fA-F]{8}", w) for w in words):
        raise ValueError("Model must be exactly 164 eight-digit hex words")
    if hashlib.sha256(data).hexdigest() != MODEL_SHA:
        raise ValueError("Model SHA-256 differs from reviewed Phase 1A package")


def find_vivado(explicit=None):
    candidates = []
    if explicit:
        # Explicit selection is strict: never silently substitute another tool.
        candidates.append(str(Path(explicit).expanduser().resolve()))
    else:
        candidates += [p for p in (shutil.which("vivado"), shutil.which("vivado.bat")) if p]
        env = os.environ.get("XILINX_VIVADO")
        if env:
            candidates += [str(Path(env) / "bin" / n) for n in ("vivado.bat", "vivado")]
        for base in ("C:/Xilinx", "C:/AMD", "C:/AMDDesignTools", "D:/Xilinx", "D:/AMD",
                     "E:/Xilinx", "E:/AMD", "/tools/Xilinx", "/opt/Xilinx", "/opt/AMD"):
            for pattern in ("Vivado/*/bin/vivado*", "*/Vivado/bin/vivado*", "Vivado/*/Vivado/bin/vivado*"):
                candidates += [str(p) for p in sorted(Path(base).glob(pattern), reverse=True)]
    candidates = list(dict.fromkeys(candidates))
    for name in candidates:
        p = Path(name)
        if p.is_file() and p.name.lower() in {"vivado", "vivado.bat", "vivado.exe"}:
            return p, candidates
    return None, candidates


def parse_timing_summary(text):
    """Read the full Design Timing Summary table; never sum a limited path list."""
    lines = text.splitlines()
    keys = ("wns_ns", "tns_ns", "setup_failing_endpoints", "setup_total_endpoints",
            "whs_ns", "ths_ns", "hold_failing_endpoints", "hold_total_endpoints",
            "wpws_ns", "tpws_ns", "pulse_failing_endpoints", "pulse_total_endpoints")
    for i, line in enumerate(lines):
        if all(token in line for token in ("WNS(ns)", "TNS(ns)", "WHS(ns)", "WPWS(ns)")):
            for row in lines[i + 1:i + 5]:
                values = row.split()
                if len(values) == 12 and all(re.fullmatch(r"-?\d+(?:\.\d+)?", v) for v in values):
                    return {k: float(v) if k.endswith("_ns") else int(v)
                            for k, v in zip(keys, values)}
    raise ValueError("No recognized full timing-summary table; inspect the raw report")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vivado", type=Path, help="Existing Vivado executable/batch path")
    parser.add_argument("--stage", choices=("synth", "route"), default="route")
    args = parser.parse_args()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "ECG":
        raise SystemExit("FAIL: run this workflow only on branch ECG")
    build = ROOT / "build/phase2b" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    build.mkdir(parents=True, exist_ok=False)
    result = {"part": "xc7z020clg484-1", "period_ns": 20.0, "mode": "out_of_context",
              "requested_stage": args.stage, "branch": branch,
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "build_directory": build.relative_to(ROOT).as_posix(), "checks": [],
              "resource_values": None, "timing_values": {}, "hardware_signoff": "NOT RUN"}
    checks = result["checks"]
    code = 1
    try:
        validate_model((ROOT / MODEL).read_bytes())
        staged = build / "input"
        hashes = {}
        for name in INPUTS:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            hashes[name] = sha(target)
            if sha(ROOT / name) != hashes[name]:
                raise ValueError(f"Source changed during staging: {name}")
        result["source_sha256"] = hashes
        result["runner_sha256"] = sha(Path(__file__))
        checks.append({"name": "source_model_preflight", "status": "PASS", "model_words": 164})
        vivado, searched = find_vivado(args.vivado)
        result["tool_discovery"] = {"executable": str(vivado) if vivado else None,
                                    "candidates": searched, "explicit": str(args.vivado) if args.vivado else None}
        if not vivado:
            for name in ("vivado_part_check", "synthesis", "implementation", "bram_mapping",
                         "rom_init_netlist_equivalence", "utilization", "setup_hold_timing"):
                checks.append({"name": name, "status": "NOT RUN", "reason": "Vivado executable unavailable; no software installed"})
            result["status"], code = "NOT RUN", 2
        else:
            command = [str(vivado), "-mode", "batch", "-log", str(build / "vivado.log"),
                       "-journal", str(build / "vivado.jou"), "-source",
                       str(staged / "synthesis/ecg/run_vivado.tcl"), "-tclargs",
                       str(build / "reports"), args.stage]
            result["command"] = command
            result["cwd"] = str(staged)
            print("RUN Vivado; transcript:", build / "console.log", flush=True)
            # Fixed tool/options, no shell=True and no user command interpolation.
            # Windows .bat launch is handled by CreateProcess/cmd; reject shell
            # metacharacters rather than attempting ad-hoc cmd quoting.
            if os.name == "nt" and any(re.search(r'[&|<>^%!\r\n]', c) for c in command):
                raise ValueError("Windows Vivado paths must not contain shell metacharacters")
            with (build / "console.log").open("w", encoding="utf-8") as log:
                run = subprocess.run(command, cwd=staged, stdout=log, stderr=subprocess.STDOUT)
            result["exit_code"] = run.returncode
            output = (build / "console.log").read_text(encoding="utf-8", errors="replace")
            result["warning_lines"] = [s for s in output.splitlines() if "WARNING:" in s]
            result["error_lines"] = [s for s in output.splitlines() if "ERROR:" in s or "FAIL ECG_" in s]
            completed = run.returncode == 0 and f"PASS ECG_VIVADO_FLOW {args.stage}" in output and not result["error_lines"]
            checks.append({"name": "vivado_command_flow", "status": "PASS" if completed else "FAIL"})
            for stage in ("synth", "route"):
                reports = build / "reports"
                complete = (reports / f"{stage}_complete.txt").is_file()
                checks.append({"name": stage, "status": "PASS" if complete else "NOT RUN"})
                if complete:
                    try:
                        result["timing_values"][stage] = parse_timing_summary(
                            (reports / f"{stage}_timing_summary.rpt").read_text())
                        checks.append({"name": stage + "_timing_table_parse", "status": "PASS"})
                    except ValueError as exc:
                        checks.append({"name": stage + "_timing_table_parse", "status": "FAIL", "reason": str(exc)})
            # Keep signoff separate from command completion: an OOC route does
            # not validate board IO, reset release, complete clock routing or ROM
            # equivalence. Raw reports must be reviewed, including unconstrained paths.
            checks.append({"name": "hardware_signoff", "status": "NOT RUN",
                           "reason": "Review raw DRC/route/coverage/ROM reports and full-system timing separately"})
            result["status"] = "FAIL" if any(e["status"] == "FAIL" for e in checks) else "PASS"
            code = 0 if result["status"] == "PASS" else 1
        result["staged_sources_unchanged"] = all(sha(staged / p) == h for p, h in hashes.items())
        if not result["staged_sources_unchanged"]:
            raise ValueError("Staged input changed during run")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        checks.append({"name": "flow_error", "status": "FAIL", "reason": str(exc)})
        result["status"], code = "FAIL", 1
    encoded = json.dumps(result, indent=2) + "\n"
    (build / "results.json").write_text(encoded, encoding="utf-8")
    summary = ROOT / "docs/phase2b_results.json"
    if summary.exists():
        summary = ROOT / "docs" / f"phase2b_results_{build.name}.json"
    with summary.open("x", encoding="utf-8") as out:
        out.write(encoded)
    for check in checks:
        print(check["status"], check["name"], flush=True)
    print(result["status"], "Vivado flow:", build, flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
