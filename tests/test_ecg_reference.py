"""Run with python -B -m unittest discover -s tests -v.

Hand-computed fixtures and a Fraction oracle are independent of the fixed datapath.
Optional runtime checks are skipped (NOT RUN) when their dependencies are absent.
"""
import ast
import importlib.util
import io
import json
import math
import pickle
import random
import struct
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ecg_reference import (CheckpointReader, FEATURES, Model, SCALE, argmax,
                           extract_features, fixed_infer, float_infer, label_from_rule,
                           legacy_word, load_checkpoint, load_model, quantize,
                           read_hex, resample_500_to_347, round_ratio_even, signed_check)
from audit_ecg_model import TRAINING, TOLERANCES, comparison, inspect_dataset, source_contract


def fraction_oracle(model, features):
    """Exact rational operations; quantize once at each specified stage."""
    q = lambda x: Fraction(round(Fraction(x) * SCALE), SCALE)
    p = [q(v) for v in model.words()]
    x = [q(v) for v in features]
    z = [q((x[i] - p[i]) * p[12 + i]) for i in range(12)]
    pre = [q(sum((z[i] * p[24 + 12 * j + i] for i in range(12)), p[120 + j])) for j in range(8)]
    h = [max(Fraction(0), v) for v in pre]
    y = [q(sum((h[i] * p[128 + 8 * j + i] for i in range(8)), p[160 + j])) for j in range(4)]
    return {k: [int(v * SCALE) for v in values]
            for k, values in (("normalized", z), ("pre_activation", pre), ("hidden", h), ("logits", y))}


def toy_model():
    w1, w2 = [0.] * 96, [0.] * 32
    for j in range(8):
        w1[j * 12 + j] = 1.
    for j in range(4):
        w2[j * 8 + j] = -2. if j == 2 else 2.
    return Model((0.,) * 12, (1.,) * 12, tuple(w1), (-.5,) * 8, tuple(w2), (1., 0., -1., -2.))


class ArithmeticTests(unittest.TestCase):
    def test_nearest_even_positive_and_negative_ties(self):
        for n, expected in ((1, 0), (3, 2), (5, 2), (-1, 0), (-3, -2), (-5, -2)):
            self.assertEqual(round_ratio_even(n, 2), expected)

    def test_rounding_matches_exact_fraction_randomly(self):
        rng = random.Random(72)
        for _ in range(1000):
            n, d = rng.randint(-10**12, 10**12), rng.randint(1, 10**8)
            self.assertEqual(round_ratio_even(n, d), round(Fraction(n, d)))

    def test_q12_20_endpoints_and_overflow(self):
        self.assertEqual(quantize(-2048.), -(1 << 31))
        self.assertEqual(quantize(2048 - 1 / SCALE), (1 << 31) - 1)
        for v in (2048., -2048 - 1 / SCALE):
            with self.assertRaises(OverflowError):
                quantize(v)

    def test_nonfinite_and_invalid_divisor_rejected(self):
        for v in (math.inf, -math.inf, math.nan):
            with self.assertRaises(ValueError):
                quantize(v)
        with self.assertRaises(ValueError):
            round_ratio_even(1, 0)

    def test_legacy_truncation_and_clipping(self):
        self.assertEqual(legacy_word(-1.5 / 4096), -1)
        self.assertEqual(legacy_word(15.), 32767)
        self.assertEqual(legacy_word(-9.), -32768)

    def test_accumulator_width_guard(self):
        self.assertEqual(signed_check((1 << 67) - 1, 68, "fixture"), (1 << 67) - 1)
        with self.assertRaises(OverflowError):
            signed_check(1 << 67, 68, "fixture")

    def test_hand_calculated_mlp_including_relu_signed_argmax(self):
        x = [-2., 1., 2., 3., 4., 5., 6., 7., 0., 0., 0., 0.]
        expected = {"normalized": x, "pre_activation": [-2.5, .5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
                    "hidden": [0., .5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5], "logits": [1., 1., -4., 3.]}
        f, q = float_infer(toy_model(), x), fixed_infer(toy_model(), x)
        for stage, values in expected.items():
            self.assertEqual(f[stage], values)
            self.assertEqual(q[stage], [int(v * SCALE) for v in values])
        self.assertEqual(f["class_id"], 3)
        self.assertEqual(q["class_id"], 3)

    def test_argmax_ties_and_all_negative(self):
        self.assertEqual(argmax([-9, -2, -2, -4]), 1)
        self.assertEqual(argmax([0, 0, 0, 0]), 0)

    def test_normalizer_overflow_is_not_saturation(self):
        m = toy_model()
        m = Model(m.means, (.01,) * 12, m.w1, m.b1, m.w2, m.b2)
        with self.assertRaisesRegex(OverflowError, "normalizer output"):
            fixed_infer(m, [100.] * 12)

    def test_layer_overflow_is_not_saturation(self):
        m = toy_model()
        m = Model(m.means, m.scales, (100.,) * 96, m.b1, m.w2, m.b2)
        with self.assertRaisesRegex(OverflowError, "layer output"):
            fixed_infer(m, [100.] * 12)

    def test_feature_count_and_scaler_validation(self):
        with self.assertRaises(ValueError):
            fixed_infer(toy_model(), [0.] * 11)
        m = toy_model()
        with self.assertRaises(ValueError):
            Model(m.means, (0.,) * 12, m.w1, m.b1, m.w2, m.b2)


class FeatureTests(unittest.TestCase):
    def test_all_twelve_hand_computed_features(self):
        result = extract_features([-1, 0, 1, 0], .5, 1.)
        r = math.sqrt(.5)
        expected = [r, .5, 1., .75, 2., 1 / (r + 1e-9), r / (r + 1e-9),
                    1., .5, 1., .5 / (1 + 1e-9), -.5]
        for a, b in zip(result, expected):
            self.assertAlmostEqual(a, b, places=14)

    def test_odd_half_window_denominators(self):
        result = extract_features([1, 1, 0], .8, .8)
        self.assertAlmostEqual(result[6], 1 / (math.sqrt(.5) + 1e-9), places=14)

    def test_zero_signal_and_rr_in_seconds(self):
        f = extract_features([0.] * 347, .5, .8)
        self.assertEqual(f[:8], [0.] * 8)
        self.assertEqual(f[8:10], [.5, .8])
        self.assertAlmostEqual(f[11], -.3)

    def test_first_last_sample_and_negative_peak(self):
        f = extract_features([2, 0, 0, -3], .8, .8)
        self.assertEqual(f[2], 3.)
        self.assertEqual(f[7], 2.)
        self.assertEqual(f[4], 5.)
        self.assertEqual(f[3], .5)

    def test_crest_fifteen_and_unbounded_half_ratio(self):
        f = extract_features([1.] + [0.] * 346, .8, .8)
        self.assertEqual(f[5], 15.)
        self.assertGreater(f[6], 2048.)
        with self.assertRaises(OverflowError):
            fixed_infer(toy_model(), f)

    def test_invalid_rr_and_empty_window(self):
        for samples, rr, previous in (([], .8, .8), ([1, 2], 0, .8), ([1, 2], .8, 0)):
            with self.assertRaises(ValueError):
                extract_features(samples, rr, previous)

    def test_four_label_rules_and_thresholds(self):
        self.assertEqual(label_from_rule("N", 60, 1, 1), 0)
        self.assertEqual(label_from_rule("N", 100, .6, .6), 0)
        self.assertEqual(label_from_rule("N", 120, .5, .5), 1)
        self.assertEqual(label_from_rule("N", 50, 1.2, 1.2), 2)
        self.assertEqual(label_from_rule("V", 75, .8, .8), 3)
        self.assertEqual(label_from_rule("N", 75, .8, 1.2), 3)
        self.assertEqual(label_from_rule("N", 75, 1.2, 1.), 0)
        self.assertEqual(label_from_rule("N", 75, 1.200001, 1.), 3)

    def test_labels_against_extracted_training_function(self):
        tree = ast.parse((TRAINING / "create_dataset.py").read_text(encoding="utf-8-sig"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_label")
        contract = source_contract(TRAINING)
        env = {"arrhythmia_minor": contract["arrhythmia_minor"], "arrhythmia_major": contract["arrhythmia_major"], "__builtins__": {"abs": abs}}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "extracted_get_label", "exec"), env)
        for sym in contract["valid_symbols"] + ["unsupported_token"]:
            for rr, previous in ((.5, .5), (.6, .6), (1., 1.), (1.2, 1.2), (.8, 1.2), (1.2, 1.)):
                self.assertEqual(label_from_rule(sym, 60 / rr, rr, previous), env["get_label"](sym, 60 / rr, rr, previous))

    def test_fourier_resampling_known_dc_sine_and_discarded_frequency(self):
        original = [1.25 + .5 * math.sin(2 * math.pi * 7 * t / 500)
                    + .1 * math.cos(2 * math.pi * 200 * t / 500) for t in range(500)]
        actual = resample_500_to_347(original)
        expected = [1.25 + .5 * math.sin(2 * math.pi * 7 * t / 347) for t in range(347)]
        self.assertLess(max(abs(a - b) for a, b in zip(actual, expected)), 1e-12)


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_model(TRAINING)
        cls.vectors = json.loads((ROOT / "tests/vectors/ecg_golden.json").read_text())

    def test_restricted_checkpoint_rejects_arbitrary_globals(self):
        with self.assertRaisesRegex(ValueError, "unsupported checkpoint global"):
            CheckpointReader(io.BytesIO(b"cos\nsystem\n.")).load()

    def test_checkpoint_matches_independent_raw_storage_decode(self):
        import zipfile
        tensors = load_checkpoint(TRAINING / "mlp_fpga_best.pth")
        with zipfile.ZipFile(TRAINING / "mlp_fpga_best.pth") as z:
            prefix = next(n[:-len("data.pkl")] for n in z.namelist() if n.endswith("/data.pkl"))
            for index, (name, count) in enumerate((("fc1.weight", 96), ("fc1.bias", 8), ("fc2.weight", 32), ("fc2.bias", 4))):
                self.assertEqual(tensors[name], struct.unpack("<" + "f" * count, z.read(prefix + f"data/{index}")))

    def test_all_164_legacy_words_and_mi_serialization(self):
        actual = read_hex(TRAINING / "weight.hex", 164)
        self.assertEqual(actual, [legacy_word(v) for v in self.model.words()])
        mi = [(int(a, 16), int(v, 16)) for line in (TRAINING / "weight.mi").read_text().splitlines()
              if not line.startswith("#") and line.strip() for a, v in [line.split(":")]]
        self.assertEqual(mi, list(enumerate(v & 0xffff for v in actual)))

    def test_confirmed_clipping_at_address_15_only(self):
        clipped = [i for i, v in enumerate(self.model.words()) if not -32768 <= int(v * 4096) <= 32767]
        self.assertEqual(clipped, [15])
        self.assertGreater(1 / self.model.scales[3], 57.)

    def test_feature_order_and_source_architecture(self):
        self.assertEqual(source_contract(TRAINING)["status"], "PASS")
        self.assertEqual(self.vectors["feature_order"], list(FEATURES))

    def test_proposed_rom_matches_rational_encoding(self):
        tokens = (ROOT / "tests/vectors/model_q12_20.hex").read_text().split()
        expected = [f"{round(Fraction(v) * SCALE) & 0xffffffff:08X}" for v in self.model.words()]
        self.assertEqual(tokens, expected)

    def test_generated_traces_match_fraction_oracle_bit_exact(self):
        for case in self.vectors["cases"]:
            with self.subTest(case=case["id"]):
                actual = fixed_infer(self.model, case["features"])
                oracle = fraction_oracle(self.model, case["features"])
                for key, expected in oracle.items():
                    self.assertEqual(actual[key], expected)
                self.assertEqual(actual, case["fixed"])
                self.assertEqual(float_infer(self.model, case["features"]), case["float"])

    def test_500_vectors_fixed_intermediates_against_fraction_oracle(self):
        words = read_hex(TRAINING / "first_500.txt", 6000)
        for index in range(0, len(words), 12):
            x = [v / 4096 for v in words[index:index + 12]]
            actual, oracle = fixed_infer(self.model, x), fraction_oracle(self.model, x)
            for stage, expected in oracle.items():
                self.assertEqual(actual[stage], expected, (index // 12, stage))

    def test_generated_vectors_float_error_budgets_and_classes(self):
        rows = [v["features"] for v in self.vectors["cases"]]
        result = comparison(self.model, rows, "candidate")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual({v["float"]["class_id"] for v in self.vectors["cases"]}, {0, 1, 2, 3})
        self.assertTrue(all(v["source_label"] is None for v in self.vectors["cases"] if v["kind"] != "source_feature_csv"))

    def test_saved_windows_and_features_recompute(self):
        for case in self.vectors["cases"]:
            if "original_window_360" in case:
                actual = resample_500_to_347(case["original_window_360"])
                self.assertEqual(actual, case["resampled_window_347"])
                self.assertEqual(extract_features(actual, *case["rr_seconds"]), case["features"])

    def test_real_golden_rows_retain_csv_features_labels_and_patient_id(self):
        import csv
        source = ROOT.parent / "datasets/AI_Training_12_Features_250Hz_V2.csv"
        cases = {c["csv_line"]: c for c in self.vectors["cases"] if c["kind"] == "source_feature_csv"}
        if not source.is_file():
            self.skipTest("NOT RUN: full feature CSV missing")
        self.assertEqual({c["source_label"] for c in cases.values()}, {0, 1, 2, 3})
        seen = set()
        with source.open(newline="", encoding="utf-8-sig") as stream:
            for line, row in enumerate(csv.DictReader(stream), 2):
                if line in cases:
                    case = cases[line]
                    self.assertEqual(case["features"], [float(row[k]) for k in FEATURES])
                    self.assertEqual(case["source_label"], int(row["label"]))
                    self.assertEqual(case["patient_id"], row["patient_id"])
                    seen.add(line)
                if seen == set(cases):
                    break
        self.assertEqual(seen, set(cases))

    def test_full_dataset_missing_is_not_500_distribution(self):
        report, examples = inspect_dataset(None)
        self.assertEqual(report["status"], "NOT RUN")
        self.assertIsNone(report["class_counts"])
        self.assertEqual(examples, [])

    def test_full_dataset_counter_and_examples_with_independent_fixture(self):
        header = "patient_id,hr,label," + ",".join(FEATURES) + "\n"
        text = header + "".join(f"patient_{i % 2},75,{label}," + ",".join(["1"] * 12) + "\n"
                               for i, label in enumerate([0, 1, 2, 3, 3]))
        with patch.object(Path, "is_file", return_value=True), patch.object(Path, "open", return_value=io.StringIO(text)), patch("audit_ecg_model.digest", return_value="fixture"):
            report, examples = inspect_dataset(Path("fixture.csv"))
        self.assertEqual(report["class_counts"], {"0": 1, "1": 1, "2": 1, "3": 2})
        self.assertEqual(report["patient_count"], 2)
        self.assertEqual(len(examples), 4)
        self.assertEqual(report["rows"], 5)

    def test_dataset_reordered_features_are_rejected(self):
        text = "patient_id,hr,label," + ",".join(reversed(FEATURES)) + "\n"
        with patch.object(Path, "is_file", return_value=True), patch.object(Path, "open", return_value=io.StringIO(text)):
            with self.assertRaisesRegex(ValueError, "columns/order"):
                inspect_dataset(Path("fixture.csv"))


class OptionalRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("torch"), "NOT RUN: PyTorch not installed")
    def test_pytorch_checkpoint_and_forward_parity(self):
        import torch
        state = torch.load(TRAINING / "mlp_fpga_best.pth", map_location="cpu", weights_only=True)
        decoded = load_checkpoint(TRAINING / "mlp_fpga_best.pth")
        for name, tensor in state.items():
            self.assertEqual(tensor.flatten().tolist(), list(decoded[name]))
        model = load_model(TRAINING)
        cases = json.loads((ROOT / "tests/vectors/ecg_golden.json").read_text())["cases"]
        for case in cases:
            expected = float_infer(model, case["features"])
            # Training normalizes in float64, then converts to FloatTensor.
            raw = torch.tensor(case["features"], dtype=torch.float64)
            means = torch.tensor(model.means, dtype=torch.float64)
            scales = torch.tensor(model.scales, dtype=torch.float64)
            z = ((raw - means) / scales).to(torch.float32)
            pre = torch.nn.functional.linear(z, state["fc1.weight"], state["fc1.bias"])
            h = torch.relu(pre)
            y = torch.nn.functional.linear(h, state["fc2.weight"], state["fc2.bias"])
            for key, tensor in (("normalized", z), ("pre_activation", pre), ("hidden", h), ("logits", y)):
                self.assertLess(max(abs(a - b) for a, b in zip(tensor.tolist(), expected[key])), 1e-4)
            self.assertEqual(y.argmax().item(), expected["class_id"])

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "NOT RUN: NumPy not installed")
    def test_numpy_original_feature_function_float64_parity(self):
        import numpy as np
        tree = ast.parse((TRAINING / "create_dataset.py").read_text(encoding="utf-8-sig"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "extract_12_features")
        env = {"np": np}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "extracted_features", "exec"), env)
        cases = json.loads((ROOT / "tests/vectors/ecg_golden.json").read_text())["cases"]
        for case in cases:
            if "resampled_window_347" in case:
                actual = env["extract_12_features"](np.array(case["resampled_window_347"], dtype=np.float64), *case["rr_seconds"])
                self.assertLess(max(abs(a - b) for a, b in zip(actual, case["features"])), 1e-12)

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "NOT RUN: SciPy not installed")
    def test_scipy_resampler_float64_and_float32_parity(self):
        import numpy as np
        from scipy.signal import resample
        case = json.loads((ROOT / "tests/vectors/ecg_golden.json").read_text())["cases"][0]
        for dtype, tolerance in ((np.float64, 1e-12), (np.float32, 2e-6)):
            actual = resample(np.array(case["original_window_360"], dtype=dtype), 347)
            self.assertLess(max(abs(float(a) - b) for a, b in zip(actual, case["resampled_window_347"])), tolerance)


if __name__ == "__main__":
    unittest.main(verbosity=2)
