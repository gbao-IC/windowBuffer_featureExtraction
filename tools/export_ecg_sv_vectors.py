"""Export SV scoreboards from immutable Phase-1A traces and independent reference.

Each inference record has 69 signed 68-bit words: inputs12, norm_products12,
normalized12, fc1_acc8, pre8, hidden8, fc2_acc4, logits4, class1.
Directed model fixtures are simulation-only; they do not replace the ECG model.
"""
import hashlib
import json
import random
from fractions import Fraction
from pathlib import Path

from ecg_reference import Model, SCALE, fixed_infer, load_model, quantize

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "tests/vectors/phase2a"
FIELDS = ("inputs", "normalizer_products", "normalized", "fc1_accumulators",
          "pre_activation", "hidden", "fc2_accumulators", "logits")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_words(path, values, bits):
    mask = (1 << bits) - 1
    path.write_text("".join(f"{v & mask:0{(bits + 3) // 4}X}\n" for v in values), encoding="ascii", newline="\n")


def flatten(trace):
    values = [v for field in FIELDS for v in trace[field]] + [trace["class_id"]]
    assert len(values) == 69
    return values


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    package = json.loads((ROOT / "tests/vectors/ecg_golden.json").read_text())
    model = load_model(ROOT.parent / "AI_FSM_ECG")
    original = [int(v, 16) for v in (ROOT / "tests/vectors/model_q12_20.hex").read_text().split()]
    assert original == [quantize(v) & 0xffffffff for v in model.words()]
    expected_hashes = json.loads((ROOT / "docs/model_manifest.json").read_text())["generated_artifacts"]
    for name, expected in expected_hashes.items():
        assert sha(ROOT / name) == expected, f"Phase-1A artifact hash mismatch: {name}"
    words = []
    for case in package["cases"]:
        actual = fixed_infer(model, case["features"])
        assert actual == case["fixed"], f"Phase-1A trace mismatch: {case['id']}"
        words.extend(flatten(actual))
    assert len(package["cases"]) == 14
    write_words(DEST / "golden.mem", words, 68)

    # Exact rational oracle, not an RTL-shaped rounding implementation.
    rounding_inputs = [0, 1, -1, (1 << 67) - 1, -(1 << 67)]
    for integer in (-2147483648, -3, -2, -1, 0, 1, 2, 3, 2147483647):
        rounding_inputs += [(integer << 20) + remainder for remainder in
                            (0, (1 << 19) - 1, 1 << 19, (1 << 19) + 1, SCALE - 1)]
    rounding_inputs += [-(1 << 51) - (1 << 19), -(1 << 51) - (1 << 19) - 1]
    rng = random.Random(20261016)
    rounding_inputs += [rng.randrange(-(1 << 67), 1 << 67) for _ in range(128)]
    arithmetic = []
    for value in rounding_inputs:
        rounded = round(Fraction(value, SCALE))
        arithmetic.extend([value, rounded, int(-(1 << 31) <= rounded < (1 << 31))])
    write_words(DEST / "arithmetic.mem", arithmetic, 68)

    w1, w2 = [0.] * 96, [0.] * 32
    for j in range(8):
        w1[j * 12 + j] = 1.5
    for j in range(4):
        w2[j * 8 + j] = -.5 if j == 2 else .5
    corner = Model((0.,) * 12, (2.,) * 12, tuple(w1), (0.,) * 8, tuple(w2), tuple(v / SCALE for v in (-2, -1, -1, -3)))
    corner_raw = [[0] * 12, [1, 3, 5, -1, -3, -5, 2, -2, 0, 0, 0, 0],
                  [2147483647, -2147483648] * 6, [-2147483648, 2147483647] * 6]
    write_words(DEST / "corner_model.hex", [quantize(v) for v in corner.words()], 32)
    write_words(DEST / "corner.mem", [v for row in corner_raw for v in flatten(fixed_infer(corner, [q / SCALE for q in row]))], 68)

    # Validate expected rejection using the unchanged Phase-1A Python reference.
    failures = []
    norm_rows = [[0] * 12 for _ in range(2)]
    norm_rows[0][3], norm_rows[1][3] = 2147483647, -2147483648
    failures.append(("norm_overflow", model, norm_rows, "normalizer output", 1))
    f1 = [0.] * 96
    f1[0] = 2.
    fc1 = Model((0.,) * 12, (1.,) * 12, tuple(f1), (0.,) * 8, (0.,) * 32, (0.,) * 4)
    failures.append(("fc1_overflow", fc1, [[2147483647] + [0] * 11, [-2147483648] + [0] * 11], "layer output", 2))
    f1[0] = 1.
    for sign, name in ((2., "fc2_positive_overflow"), (-2., "fc2_negative_overflow")):
        f2 = [sign] + [0.] * 31
        fixture = Model((0.,) * 12, (1.,) * 12, tuple(f1), (0.,) * 8, tuple(f2), (0.,) * 4)
        failures.append((name, fixture, [[2147483647] + [0] * 11], "layer output", 3))
    failure_info = []
    for name, fixture, rows, error_text, stage in failures:
        for row in rows:
            try:
                fixed_infer(fixture, [q / SCALE for q in row])
            except OverflowError as exc:
                assert error_text in str(exc), str(exc)
            else:
                raise AssertionError(f"{name} did not overflow")
        rejected = [v for row in rows for v in row + [0] * 57]
        # A successful inference immediately after errors verifies sticky status
        # clears on acceptance, without resetting or changing the loaded model.
        recovery = flatten(fixed_infer(fixture, [0.] * 12))
        write_words(DEST / f"{name}.mem", rejected + recovery, 68)
        write_words(DEST / f"{name}_model.hex", [quantize(v) for v in fixture.words()], 32)
        failure_info.append({"name": name, "cases": len(rows), "error_stage": stage, "recovery_case": len(rows)})

    info = {"status": "PASS", "record_words": 69, "golden_cases": len(package["cases"]),
            "golden_ids": [c["id"] for c in package["cases"]], "corner_cases": len(corner_raw),
            "arithmetic_cases": len(rounding_inputs), "failure_suites": failure_info,
            "source_hashes": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in
                              (ROOT / "tests/vectors/ecg_golden.json", ROOT / "tests/vectors/model_q12_20.hex", ROOT / "tools/ecg_reference.py")},
            "generated_hashes": {p.name: sha(p) for p in sorted(DEST.iterdir()) if p.suffix in (".hex", ".mem")}}
    (DEST / "manifest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: exported 14 unchanged golden cases, {len(corner_raw)} signed cases, {len(rounding_inputs)} arithmetic cases, 6 expected overflow cases")


if __name__ == "__main__":
    main()
