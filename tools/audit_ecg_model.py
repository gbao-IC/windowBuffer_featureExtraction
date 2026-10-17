"""Reproduce Phase 1A artifacts without executing or writing training code.

python -B tools/audit_ecg_model.py --output-root .
python -B tools/audit_ecg_model.py --check --output-root .
Optional: --dataset PATH_TO_FULL_FEATURE_CSV (never inferred from 500 vectors).
Exit 1 means a diagnostic FAIL, even if artifact generation succeeds.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

from ecg_reference import (BITS, BLOCKS, FEATURES, FRAC, LABELS, SCALE, SHAPES,
                           extract_features, fixed_infer, float_infer,
                           label_from_rule, legacy_parameter_infer, legacy_word,
                           load_model, quantize, read_hex, resample_500_to_347)

ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT.parent / "AI_FSM_ECG"
TOLERANCES = {"normalized": .001, "pre_activation": .002, "hidden": .002, "logits": .01}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def literal_assignment(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"missing literal assignment: {name}")


def source_contract(training):
    create = ast.parse((training / "create_dataset.py").read_text(encoding="utf-8-sig"))
    train = ast.parse((training / "train_2.py").read_text(encoding="utf-8-sig"))
    export = ast.parse((training / "convert_to_hex.py").read_text(encoding="utf-8-sig"))
    ordered = literal_assignment(create, "feature_cols")
    fn = next(n for n in create.body if isinstance(n, ast.FunctionDef) and n.name == "extract_12_features")
    returned = next(n.value for n in ast.walk(fn) if isinstance(n, ast.Return))
    return_order = [n.id for n in returned.elts]
    linears = []
    for tree in (train, export):
        linears.append([tuple(ast.literal_eval(a) for a in n.args) for n in ast.walk(tree)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == "nn" and n.func.attr == "Linear"])
    dynamic = next(n.value for n in train.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "feature_cols" for t in n.targets))
    expected_selector = ast.parse("[c for c in df.columns if c.startswith('f_')]", mode="eval").body
    saves = [n for n in ast.walk(train) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "torch" and n.func.attr == "save"]
    exact = ordered == list(FEATURES) == return_order and linears == [[(12, 8), (8, 4)]] * 2
    exact = exact and ast.dump(dynamic) == ast.dump(expected_selector)
    return {"status": "PASS" if exact else "FAIL", "declared_feature_order": ordered,
            "return_feature_order": return_order, "train_and_export_linear_shapes": linears,
            "training_feature_selection": ast.unparse(dynamic),
            "csv_order_verified": "NOT RUN", "torch_save_call_count": len(saves),
            "valid_symbols": literal_assignment(create, "valid_symbols"),
            "arrhythmia_minor": literal_assignment(create, "arrhythmia_minor"),
            "arrhythmia_major": literal_assignment(create, "arrhythmia_major")}


def inspect_dataset(path):
    """Streaming full CSV count; return first source row/class for Stage-A replay."""
    if path is None or not Path(path).is_file():
        return {"status": "NOT RUN", "reason": "Full feature CSV and raw ECG/annotations unavailable; 500 vectors are a separate population.",
                "class_counts": None, "patient_count": None}, []
    path = Path(path)
    counts, patients, examples = Counter(), set(), {}
    low, high = [math.inf] * 12, [-math.inf] * 12
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or [c for c in fields if c.startswith("f_")] != list(FEATURES):
            raise ValueError("dataset f_ columns/order do not match reference")
        if not {"patient_id", "label", "hr"}.issubset(fields):
            raise ValueError("missing dataset metadata columns")
        for row_number, row in enumerate(reader, 2):
            label = int(row["label"])
            values = [float(row[k]) for k in FEATURES]
            if label not in LABELS or not all(math.isfinite(v) for v in values):
                raise ValueError(f"invalid dataset row {row_number}")
            if not row["patient_id"] or not math.isfinite(float(row["hr"])):
                raise ValueError(f"invalid metadata row {row_number}")
            counts[label] += 1
            patients.add(row["patient_id"])
            low = [min(a, b) for a, b in zip(low, values)]
            high = [max(a, b) for a, b in zip(high, values)]
            examples.setdefault(label, {"id": f"dataset_class_{label}", "kind": "source_feature_csv",
                                        "csv_line": row_number, "patient_id": row["patient_id"],
                                        "source_label": label, "features": values,
                                        "samples_status": "NOT RUN: feature CSV has no raw window"})
    if not counts:
        raise ValueError("empty dataset")
    return {"status": "PASS", "file_name": path.name, "sha256": digest(path),
            "rows": sum(counts.values()), "class_counts": {str(k): counts[k] for k in LABELS},
            "patient_count": len(patients), "feature_min": low, "feature_max": high,
            "all_four_classes": "PASS" if len(counts) == 4 else "FAIL",
            "patient_split_overlap": "NOT RUN: saved train/val/test membership unavailable"}, list(examples.values())


def synthetic_cases(model):
    cases = []
    original = [((i % 50) - 25) / 128 + (1.5 if i == 250 else 0.) for i in range(500)]
    window = resample_500_to_347(original)
    for label, rr, symbol in ((0, .8, "N"), (1, .5, "N"), (2, 1.2, "N"), (3, .8, "V")):
        cases.append({"id": f"synthetic_rule_{label}", "kind": "synthetic_waveform_not_patient_data",
                      "source_label": None, "rule_label": label_from_rule(symbol, 60 / rr, rr, rr),
                      "symbol": symbol, "rr_seconds": [rr, rr], "original_window_360": original,
                      "resampled_window_347": window, "features": extract_features(window, rr, rr)})
    # Arithmetic coverage only: these feature vectors are not physiological ECG.
    rng, seen = random.Random(20261016), set()
    for attempt in range(10000):
        x = [m + s * rng.uniform(-3, 3) for m, s in zip(model.means, model.scales)]
        label = float_infer(model, x)["class_id"]
        if label not in seen:
            seen.add(label)
            cases.append({"id": f"synthetic_output_{label}", "kind": "nonphysiological_arithmetic_probe",
                          "source_label": None, "search_attempt": attempt, "features": x})
        if len(seen) == 4:
            break
    cases.append({"id": "mean_input", "kind": "normalizer_zero_probe", "source_label": None,
                  "features": list(model.means)})
    cases.append({"id": "crest_15", "kind": "out_of_legacy_range_probe", "source_label": None,
                  "features": list(model.means[:5]) + [15.] + list(model.means[6:])})
    return cases


def comparison(model, rows, mode):
    maximum = {k: 0. for k in TOLERANCES}
    mismatch, overflows, processed = [], [], 0
    min_margin = math.inf
    for index, x in enumerate(rows):
        ref = float_infer(model, x)
        try:
            actual = fixed_infer(model, x) if mode == "candidate" else legacy_parameter_infer(model, x)
        except OverflowError as exc:
            overflows.append({"index": index, "error": str(exc)})
            continue
        processed += 1
        for key in maximum:
            values = [v / SCALE for v in actual[key]] if mode == "candidate" else actual[key]
            maximum[key] = max(maximum[key], max(abs(a - b) for a, b in zip(ref[key], values)))
        if actual["class_id"] != ref["class_id"]:
            mismatch.append(index)
        sorted_logits = sorted(ref["logits"], reverse=True)
        min_margin = min(min_margin, sorted_logits[0] - sorted_logits[1])
    ok = not mismatch and not overflows and all(maximum[k] <= TOLERANCES[k] for k in maximum)
    return {"status": "PASS" if ok and processed else "FAIL", "vectors": len(rows), "processed": processed,
            "max_absolute_errors": maximum, "class_mismatch_indices": mismatch,
            "overflow_errors": overflows, "minimum_float_logit_margin": min_margin if processed else None,
            "acceptance_tolerances": TOLERANCES, "clinical_or_dataset_accuracy": "NOT RUN"}


def build_artifacts(training=TRAINING, dataset=None):
    model = load_model(training)
    source = source_contract(training)
    words, original = model.words(), read_hex(training / "weight.hex", 164)
    reproduced = [legacy_word(v) for v in words]
    clips = [{"address": i, "block": next(n for n, s, count in BLOCKS if s <= i < s + count),
              "unquantized": v, "unclamped_integer": int(v * 4096),
              "stored_signed": reproduced[i], "stored_value": reproduced[i] / 4096}
             for i, v in enumerate(words) if not -32768 <= int(v * 4096) <= 32767]
    legacy_raw = read_hex(training / "first_500.txt", 6000)
    legacy_rows = [[v / 4096 for v in legacy_raw[i:i + 12]] for i in range(0, 6000, 12)]
    labels = [int(v) for v in (training / "label.txt").read_text().split()]
    if len(labels) != 500 or any(v not in LABELS for v in labels):
        raise ValueError("invalid legacy label file")
    ds, dataset_cases = inspect_dataset(dataset)
    if ds["status"] == "PASS":
        source["csv_order_verified"] = "PASS"
    cases = synthetic_cases(model) + dataset_cases
    for case in cases:
        case["float"] = float_infer(model, case["features"])
        try:
            case["fixed"] = fixed_infer(model, case["features"])
        except OverflowError as exc:
            case["fixed"] = {"status": "FAIL", "error": str(exc)}
    candidates = [c["features"] for c in cases]
    qwords = [quantize(v) for v in words]
    candidate_hex = ("\n".join(f"{v & 0xffffffff:08X}" for v in qwords) + "\n").encode("ascii")
    vectors = {"schema": "ecg-golden-v1", "provenance": "Synthetic probes; source CSV examples only when explicitly supplied.",
               "float_arithmetic": "binary64, math.fsum dot products; not PyTorch float32 bit identity",
               "fixed_arithmetic": "signed32 fractional20, RNE, overflow raises; proposed contract only",
               "feature_order": FEATURES, "cases": cases}
    vector_data = json_bytes(vectors)
    results = {
        "source_contract": source,
        "checkpoint_layout": {"status": "PASS", "shapes": SHAPES, "storage_dtype": "IEEE754 float32 little endian",
                              "method": "restricted metadata decoder and binary float storage; no torch import"},
        "legacy_rom_reproduction": {"status": "PASS" if original == reproduced else "FAIL", "words": len(words),
                                    "mismatch_addresses": [i for i, (a, b) in enumerate(zip(original, reproduced)) if a != b]},
        "legacy_no_clipping": {"status": "FAIL" if clips else "PASS", "clipped_parameters": clips},
        "checkpoint_scaler_training_provenance": {"status": "FAIL", "reason": "train_2.py never calls torch.save; scaler is rewritten before loading pre-existing checkpoint. Same-run pairing cannot be established."},
        "patient_disjoint_split": {"status": "FAIL", "reason": "Two stratified row-level train_test_split calls; patient_id not used. Actual overlap NOT RUN without dataset and split membership."},
        "annotation_semantics": {"status": "NOT RUN", "reason": "No raw annotations or upstream dataset schema. Allowlist includes punctuation; clinical meaning not inferred."},
        "full_dataset": ds,
        "legacy_500_population": {"status": "PASS", "vectors": 500, "words": 6000,
                                  "label_counts": {str(k): labels.count(k) for k in LABELS},
                                  "encoding_provenance": "NOT RUN: signed Q4.12 raw-feature decoding is only a comparison hypothesis",
                                  "all_four_classes": "FAIL" if len(set(labels)) != 4 else "PASS"},
        "candidate_constants": {"status": "PASS", "word_count": len(qwords), "clipped": 0,
                                "max_abs_error": max(abs(a - b / SCALE) for a, b in zip(words, qwords))},
        "candidate_vs_float_on_legacy_decode_hypothesis": comparison(model, legacy_rows, "candidate"),
        "legacy_parameters_vs_float_on_legacy_decode_hypothesis": comparison(model, legacy_rows, "legacy"),
        "candidate_vs_float_on_generated_vectors": comparison(model, candidates, "candidate"),
        "generated_prediction_coverage": {"status": "PASS" if {c["float"]["class_id"] for c in cases} == set(LABELS) else "FAIL",
                                          "float_classes": sorted({c["float"]["class_id"] for c in cases}),
                                          "kind": "synthetic coverage does not establish source-data class coverage"},
        "source_data_four_class_vectors": {"status": "PASS" if len(dataset_cases) == 4 else "FAIL" if ds["status"] == "PASS" else "NOT RUN",
                                           "count": len(dataset_cases), "reason": "Source feature rows preserved with CSV line and patient ID; raw-window lineage still unavailable."},
        "pytorch_numpy_scipy_runtime_parity": {"status": "NOT RUN", "reason": "Optional dependency tests report installed-runtime status separately."},
        "rtl_hardware_parity": {"status": "NOT RUN", "reason": "Phase 1A changes no RTL. Experimental Q12.20 is not implemented in RTL."},
    }
    manifest = {"schema": "ecg-model-package-audit-v1", "training_commit": "7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d",
                "package_status": "FAIL: legacy clipping and unproven checkpoint/scaler training pairing",
                "feature_order": FEATURES, "labels": LABELS, "network": [12, 8, 4], "activation": "ReLU", "output": "logits; argmax lowest-index tie",
                "inputs": {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(training.iterdir()) if p.is_file()},
                "feature_dataset": ds,
                "serialization": [{"name": n, "first_address": s, "count": count} for n, s, count in BLOCKS],
                "weight_orientation": "output-neuron-major, then input feature; contiguous C order",
                "legacy": {"bits": 16, "fractional_bits": 12, "rounding": "truncate toward zero then saturate", "clipped": clips},
                "candidate": {"status": "PROPOSED, not an approved/retrained/deployable model", "bits": BITS, "fractional_bits": FRAC,
                              "range": [-2048, 2048 - 1 / SCALE], "rounding": "nearest ties to even", "overflow": "reject, never silently saturate",
                              "subtraction_bits": 33, "normalizer_product_bits": 65, "mac_product_bits": 64, "accumulator_bits": 68,
                              "accumulator_fractional_bits": 40, "bias_alignment": "left shift 20; round only after full dot product",
                              "requires": "Dataset range audit, accuracy/margin acceptance, and hardware width/cost approval. No finite format covers unconstrained half_ratio."},
                "generated_artifacts": {"tests/vectors/ecg_golden.json": hashlib.sha256(vector_data).hexdigest(),
                                        "tests/vectors/model_q12_20.hex": hashlib.sha256(candidate_hex).hexdigest()},
                "generators": {"tools/ecg_reference.py": digest(ROOT / "tools/ecg_reference.py"),
                               "tools/audit_ecg_model.py": digest(ROOT / "tools/audit_ecg_model.py")}}
    return {"docs/model_manifest.json": json_bytes(manifest), "docs/phase1a_results.json": json_bytes(results),
            "tests/vectors/ecg_golden.json": vector_data, "tests/vectors/model_q12_20.hex": candidate_hex}, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-dir", type=Path, default=TRAINING)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="compare committed/candidate artifacts without writing")
    args = parser.parse_args()
    dataset = args.dataset or ROOT.parent / "datasets/AI_Training_12_Features_250Hz_V2.csv"
    artifacts, results = build_artifacts(args.training_dir, dataset)
    artifact_ok = True
    for name, content in artifacts.items():
        path = args.output_root / name
        if args.check:
            ok = path.is_file() and path.read_bytes() == content
            artifact_ok &= ok
            print(f"{'PASS' if ok else 'FAIL'} reproducibility: {name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"PASS generated: {name}")
    for name, result in results.items():
        print(f"{result['status']} {name}")
    return 1 if not artifact_ok or any(v["status"] == "FAIL" for v in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
