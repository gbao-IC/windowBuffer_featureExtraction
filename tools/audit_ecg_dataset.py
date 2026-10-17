"""Full-population numeric audit; optional exact sklearn split/scaler recreation.

Does not train, save a checkpoint, or write input data. The full-population scores
are descriptive checkpoint-label agreement, NOT independently validated accuracy.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import platform
from pathlib import Path

from audit_ecg_model import ROOT, TRAINING, TOLERANCES, digest, inspect_dataset, json_bytes
from ecg_reference import (FEATURES, SCALE, fixed_infer, float_infer,
                           legacy_parameter_infer, load_model)


def runtime_split_check(path, model):
    names = ("numpy", "pandas", "sklearn")
    if any(importlib.util.find_spec(n) is None for n in names):
        return {"status": "NOT RUN", "reason": "Requires numpy, pandas, scikit-learn in the active interpreter."}
    import numpy as np
    import pandas as pd
    import sklearn
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    df = pd.read_csv(path)
    columns = [c for c in df.columns if c.startswith("f_")]
    if columns != list(FEATURES):
        raise ValueError("pandas dataset feature order mismatch")
    x, y = df[columns].values, df["label"].values
    train, rest = train_test_split(np.arange(len(df)), test_size=.3, stratify=y, random_state=42)
    val, test = train_test_split(rest, test_size=.5, stratify=y[rest], random_state=42)
    fitted = StandardScaler().fit(x[train])
    mean_error = np.abs(fitted.mean_ - np.array(model.means))
    scale_error = np.abs(fitted.scale_ - np.array(model.scales))
    sets = {name: set(df.iloc[idx]["patient_id"].astype(str)) for name, idx in (("train", train), ("validation", val), ("test", test))}
    intersections = {"train_validation": sorted(sets["train"] & sets["validation"]),
                     "train_test": sorted(sets["train"] & sets["test"]),
                     "validation_test": sorted(sets["validation"] & sets["test"])}
    matched = float(max(mean_error.max(), scale_error.max())) <= 1e-12
    return {"status": "PASS" if matched else "FAIL", "absolute_tolerance": 1e-12,
            "mean_max_abs_error": float(mean_error.max()), "scale_max_abs_error": float(scale_error.max()),
            "mean_errors": mean_error.tolist(), "scale_errors": scale_error.tolist(),
            "fitted_mean": fitted.mean_.tolist(), "fitted_scale": fitted.scale_.tolist(),
            "versions": {"numpy": np.__version__, "pandas": pd.__version__, "scikit-learn": sklearn.__version__},
            "splits": {name: {"rows": len(idx), "patients": len(sets[name]),
                               "class_counts": {str(k): int((y[idx] == k).sum()) for k in range(4)}}
                       for name, idx in (("train", train), ("validation", val), ("test", test))},
            "patient_disjoint": {"status": "FAIL" if any(intersections.values()) else "PASS", "overlap_ids": intersections},
            "limitation": "Reconstructed split from current CSV/code; matching scaler does not establish checkpoint save history or held-out provenance."}


def population_numeric_check(path, model):
    stages = tuple(TOLERANCES)
    errors = {mode: {key: 0. for key in stages} for mode in ("candidate", "legacy_parameters")}
    maxima = {key: 0. for key in stages}
    confusion = {mode: [[0] * 4 for _ in range(4)] for mode in ("float", "candidate", "legacy_parameters")}
    mismatch = {mode: [] for mode in errors}
    mismatch_counts = dict.fromkeys(errors, 0)
    overflow_count, overflows = 0, []
    raw_q4_outside = [0] * 12
    raw_q4_export_clips = [0] * 12
    min_margin = math.inf
    raw_error, rows = 0., 0
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            x = [float(row[f]) for f in FEATURES]
            label = int(row["label"])
            for i, v in enumerate(x):
                raw_q4_outside[i] += int(not -8 <= v <= 32767 / 4096)
                raw_q4_export_clips[i] += int(not -32768 <= int(v * 4096) <= 32767)
            ref = float_infer(model, x)
            confusion["float"][label][ref["class_id"]] += 1
            sorted_logits = sorted(ref["logits"], reverse=True)
            margin = sorted_logits[0] - sorted_logits[1]
            min_margin = min(min_margin, margin)
            for key in stages:
                maxima[key] = max(maxima[key], max(abs(v) for v in ref[key]))
            try:
                candidate = fixed_infer(model, x)
                raw_error = max(raw_error, max(abs(a - b / SCALE) for a, b in zip(x, candidate["inputs"])))
            except OverflowError as exc:
                candidate = None
                overflow_count += 1
                if len(overflows) < 20:
                    overflows.append({"csv_line": rows + 2, "error": str(exc)})
            legacy = legacy_parameter_infer(model, x)
            for mode, actual in (("candidate", candidate), ("legacy_parameters", legacy)):
                if actual is None:
                    continue
                confusion[mode][label][actual["class_id"]] += 1
                if actual["class_id"] != ref["class_id"]:
                    mismatch_counts[mode] += 1
                    if len(mismatch[mode]) < 25:
                        mismatch[mode].append({"csv_line": rows + 2, "patient_id": row["patient_id"],
                                               "source_label": label, "float_class": ref["class_id"],
                                               "actual_class": actual["class_id"], "float_margin": margin})
                for key in stages:
                    values = [v / SCALE for v in actual[key]] if mode == "candidate" else actual[key]
                    errors[mode][key] = max(errors[mode][key], max(abs(a - b) for a, b in zip(ref[key], values)))
            rows += 1
            if rows % 20000 == 0:
                print(f"Processed {rows} source feature rows", flush=True)
    numeric_ok = overflow_count == 0 and all(errors["candidate"][k] <= TOLERANCES[k] for k in stages)
    return {"status": "PASS" if numeric_ok and mismatch_counts["candidate"] == 0 else "FAIL",
            "rows": rows, "candidate_stage_error_budget": "PASS" if numeric_ok else "FAIL",
            "candidate_class_identity": "PASS" if mismatch_counts["candidate"] == 0 and not overflow_count else "FAIL",
            "tolerances": TOLERANCES, "max_absolute_errors": errors,
            "float_stage_max_abs": maxima, "candidate_input_max_abs_error": raw_error,
            "candidate_overflow_count": overflow_count, "overflow_examples": overflows,
            "class_mismatch_counts_vs_float": mismatch_counts, "class_mismatch_examples": mismatch,
            "minimum_float_logit_margin": min_margin,
            "raw_q4_12_out_of_range_by_feature": dict(zip(FEATURES, raw_q4_outside)),
            "raw_q4_12_export_clamp_count_by_feature": dict(zip(FEATURES, raw_q4_export_clips)),
            "confusion_rows_label_columns_prediction": confusion,
            "descriptive_full_pool_label_agreement": {mode: sum(matrix[i][i] for i in range(4)) / rows for mode, matrix in confusion.items()},
            "held_out_accuracy": "NOT RUN: checkpoint training membership/save provenance unknown; full pool is not a held-out test",
            "legacy_scope": "Parameter quantization only, binary64 arithmetic and unquantized source features; NOT existing RTL emulation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT.parent / "datasets/AI_Training_12_Features_250Hz_V2.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/phase1a_dataset_results.json")
    parser.add_argument("--scaler-only", action="store_true", help="refresh split/scaler runtime check, retaining hash-matched full numeric results")
    args = parser.parse_args()
    dataset, _ = inspect_dataset(args.dataset)
    model = load_model(TRAINING)
    if args.scaler_only:
        results = json.loads(args.output.read_text(encoding="utf-8"))
        if results["dataset"].get("sha256") != dataset.get("sha256") or dataset["status"] != "PASS":
            raise ValueError("cannot reuse numeric results from a different dataset")
        if results["source_hashes"]["tools/ecg_reference.py"] != digest(ROOT / "tools/ecg_reference.py"):
            raise ValueError("reference changed; run full numeric audit again")
        results["scaler_reconstruction"] = runtime_split_check(args.dataset, model)
        args.output.write_bytes(json_bytes(results))
        print(f"{results['scaler_reconstruction']['status']} scaler_reconstruction", flush=True)
        return int(results["scaler_reconstruction"]["status"] == "FAIL")
    results = {"python_version": platform.python_version(), "dataset": dataset,
               "source_hashes": {"tools/audit_ecg_dataset.py": digest(Path(__file__)),
                                 "tools/ecg_reference.py": digest(ROOT / "tools/ecg_reference.py")},
               "preprocessing_from_raw": {"status": "NOT RUN", "reason": "Only feature CSV supplied; no raw ECG or annotations."}}
    if dataset["status"] == "PASS":
        results["scaler_reconstruction"] = runtime_split_check(args.dataset, model)
        print(f"{results['scaler_reconstruction']['status']} scaler_reconstruction", flush=True)
        results["full_population_numeric"] = population_numeric_check(args.dataset, model)
    else:
        results["scaler_reconstruction"] = {"status": "NOT RUN", "reason": "No dataset"}
        results["full_population_numeric"] = {"status": "NOT RUN", "reason": "No dataset"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json_bytes(results))
    for key in ("dataset", "scaler_reconstruction", "full_population_numeric", "preprocessing_from_raw"):
        print(f"{results[key]['status']} {key}", flush=True)
    return 1 if any(v.get("status") == "FAIL" for v in results.values() if isinstance(v, dict)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
