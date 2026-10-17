"""Independent, standard-library ECG references; never imports training modules.

Float calculations use binary64, not PyTorch's float32 accumulation. Fixed inference
is an experimental Stage-A contract (32 bits, 20 fractional bits), not existing RTL.
"""
from __future__ import annotations

import csv
import io
import math
import pickle
import struct
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FEATURES = (
    "f_rms", "f_var", "f_peak", "f_zc", "f_ptp", "f_crest",
    "f_half_ratio", "f_max", "f_rr", "f_rr_prev", "f_rr_ratio", "f_rr_diff",
)
LABELS = {0: "Normal", 1: "Fast", 2: "Slow", 3: "Abnormal"}
SHAPES = {"fc1.weight": (8, 12), "fc1.bias": (8,),
          "fc2.weight": (4, 8), "fc2.bias": (4,)}
BLOCKS = (("mean", 0, 12), ("inverse_scale", 12, 12), ("fc1.weight", 24, 96),
          ("fc1.bias", 120, 8), ("fc2.weight", 128, 32), ("fc2.bias", 160, 4))
BITS, FRAC = 32, 20
SCALE = 1 << FRAC


def finite(values):
    result = tuple(float(x) for x in values)
    if not all(math.isfinite(x) for x in result):
        raise ValueError("non-finite numeric input")
    return result


@dataclass(frozen=True)
class Model:
    means: tuple
    scales: tuple
    w1: tuple
    b1: tuple
    w2: tuple
    b2: tuple

    def __post_init__(self):
        for name, size in (("means", 12), ("scales", 12), ("w1", 96),
                           ("b1", 8), ("w2", 32), ("b2", 4)):
            values = finite(getattr(self, name))
            if len(values) != size:
                raise ValueError(f"{name}: expected {size} values")
            object.__setattr__(self, name, values)
        if min(self.scales) <= 0:
            raise ValueError("scales must be positive")

    def words(self):
        return self.means + tuple(1 / s for s in self.scales) + self.w1 + self.b1 + self.w2 + self.b2


class _FloatStorage:
    """Inert marker; no torch object is constructed."""


@dataclass(frozen=True)
class _Storage:
    key: str
    count: int


def _tensor(storage, offset, shape, stride, requires_grad, hooks):
    if not isinstance(storage, _Storage) or requires_grad or hooks:
        raise ValueError("unsupported tensor metadata")
    return (storage, offset, shape, stride)


class CheckpointReader(pickle.Unpickler):
    """Narrow whitelist for this state_dict; rejects arbitrary pickle globals."""
    def find_class(self, module, name):
        allowed = {("collections", "OrderedDict"): OrderedDict,
                   ("torch", "FloatStorage"): _FloatStorage,
                   ("torch._utils", "_rebuild_tensor_v2"): _tensor}
        if (module, name) not in allowed:
            raise ValueError(f"unsupported checkpoint global: {module}.{name}")
        return allowed[module, name]

    def persistent_load(self, pid):
        if (not isinstance(pid, tuple) or len(pid) != 5 or pid[0] != "storage"
                or pid[1] is not _FloatStorage or pid[3] != "cpu"
                or not isinstance(pid[2], str) or not pid[2].isdigit()
                or type(pid[4]) is not int or not 0 < pid[4] <= 96):
            raise ValueError("unsupported storage descriptor")
        return _Storage(pid[2], pid[4])


def load_checkpoint(path):
    with zipfile.ZipFile(path) as archive:
        entries = [n for n in archive.namelist() if n.endswith("/data.pkl")]
        if len(entries) != 1:
            raise ValueError("expected one PyTorch state_dict")
        prefix = entries[0][:-len("data.pkl")]
        if archive.read(prefix + "byteorder").strip() != b"little":
            raise ValueError("only little-endian float32 checkpoint is supported")
        state = CheckpointReader(io.BytesIO(archive.read(entries[0]))).load()
        if not isinstance(state, OrderedDict) or set(state) != set(SHAPES):
            raise ValueError("checkpoint keys do not match 12-8-4 network")
        tensors, used = {}, set()
        for name, shape in SHAPES.items():
            storage, offset, actual_shape, stride = state[name]
            expected_stride = (shape[1], 1) if len(shape) == 2 else (1,)
            if (actual_shape != shape or stride != expected_stride or offset != 0
                    or storage.count != math.prod(shape) or storage.key in used):
                raise ValueError(f"unexpected layout: {name}")
            used.add(storage.key)
            raw = archive.read(prefix + "data/" + storage.key)
            if len(raw) != storage.count * 4:
                raise ValueError(f"incorrect storage length: {name}")
            tensors[name] = finite(struct.unpack("<" + "f" * storage.count, raw))
        return tensors


def load_model(training_dir):
    root = Path(training_dir)
    tensors = load_checkpoint(root / "mlp_fpga_best.pth")
    with (root / "scaler_params_fpga.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["mean", "scale"]:
            raise ValueError("unexpected scaler columns")
        rows = list(reader)
    return Model(tuple(float(r["mean"]) for r in rows), tuple(float(r["scale"]) for r in rows),
                 tensors["fc1.weight"], tensors["fc1.bias"], tensors["fc2.weight"], tensors["fc2.bias"])


def argmax(values):
    """Lowest index wins a tie, matching torch.max(dim=1)."""
    return max(range(len(values)), key=values.__getitem__)


def float_infer(model, features):
    x = finite(features)
    if len(x) != 12:
        raise ValueError("expected exactly 12 features")
    normalized = [(x[i] - model.means[i]) / model.scales[i] for i in range(12)]
    pre = [math.fsum([model.b1[j]] + [normalized[i] * model.w1[j * 12 + i]
                                    for i in range(12)]) for j in range(8)]
    hidden = [max(0.0, v) for v in pre]
    logits = [math.fsum([model.b2[j]] + [hidden[i] * model.w2[j * 8 + i]
                                      for i in range(8)]) for j in range(4)]
    finite(normalized + pre + hidden + logits)
    return {"normalized": normalized, "pre_activation": pre, "hidden": hidden,
            "logits": logits, "class_id": argmax(logits)}


def signed_check(value, bits, stage):
    if not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
        raise OverflowError(f"{stage}: {value} does not fit signed {bits} bits")
    return value


def round_ratio_even(numerator, denominator):
    """Nearest integer, ties to even, including negative numbers."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    q, remainder = divmod(numerator, denominator)
    return q + int(2 * remainder > denominator or (2 * remainder == denominator and q % 2))


def quantize(value, bits=BITS, frac=FRAC):
    value = finite([value])[0]
    numerator, denominator = value.as_integer_ratio()
    return signed_check(round_ratio_even(numerator << frac, denominator), bits, "quantization")


def legacy_word(value):
    """Exact algorithm of convert_to_hex.py: truncate then clamp."""
    return max(-32768, min(32767, int(value * 4096)))


def read_hex(path, count=None):
    tokens = Path(path).read_text(encoding="ascii").split()
    if count is not None and len(tokens) != count:
        raise ValueError(f"{path}: expected {count} words, got {len(tokens)}")
    if any(len(t) != 4 or any(c not in "0123456789abcdefABCDEF" for c in t) for t in tokens):
        raise ValueError("expected one 16-bit hexadecimal word per token")
    return [int(t, 16) - (65536 if int(t, 16) >= 32768 else 0) for t in tokens]


@lru_cache(maxsize=8)
def encoded_parameters(model):
    return tuple(quantize(v) for v in model.words())


def fixed_infer(model, features):
    """Integer-only inference after encoding. RNE once per layer; no silent clipping.

    All stored data/parameters: signed32 Q12.20. Subtraction: signed33.
    Normalizer product: signed65 Q40. MAC products: signed64 Q40.
    Bias is shifted left20; accumulator: signed68 Q40. Output: signed32 Q20.
    """
    x = [quantize(v) for v in features]
    if len(x) != 12:
        raise ValueError("expected exactly 12 features")
    p = encoded_parameters(model)
    norm_products, normalized = [], []
    for i in range(12):
        delta = signed_check(x[i] - p[i], 33, "normalizer subtraction")
        product = signed_check(delta * p[12 + i], 65, "normalizer product")
        norm_products.append(product)
        normalized.append(signed_check(round_ratio_even(product, SCALE), 32, "normalizer output"))

    def layer(inputs, weight_offset, bias_offset, count):
        accumulators, output = [], []
        for j in range(count):
            acc = signed_check(p[bias_offset + j] << FRAC, 68, "bias alignment")
            for i, val in enumerate(inputs):
                product = signed_check(val * p[weight_offset + j * len(inputs) + i], 64, "MAC product")
                acc = signed_check(acc + product, 68, "MAC accumulator")
            accumulators.append(acc)
            output.append(signed_check(round_ratio_even(acc, SCALE), 32, "layer output"))
        return accumulators, output

    acc1, pre = layer(normalized, 24, 120, 8)
    hidden = [max(0, v) for v in pre]
    acc2, logits = layer(hidden, 128, 160, 4)
    return {"inputs": x, "normalizer_products": norm_products,
            "normalized": normalized, "fc1_accumulators": acc1,
            "pre_activation": pre, "hidden": hidden, "fc2_accumulators": acc2,
            "logits": logits, "class_id": argmax(logits)}


def legacy_parameter_infer(model, features):
    """Float arithmetic with original Q4.12 ROM parameters; isolates parameter loss.

    Does NOT emulate any existing RTL arithmetic or its known control defects.
    """
    p = [legacy_word(v) / 4096 for v in model.words()]
    z = [(x - p[i]) * p[12 + i] for i, x in enumerate(features)]
    pre = [math.fsum([p[120 + j]] + [z[i] * p[24 + j * 12 + i] for i in range(12)]) for j in range(8)]
    h = [max(0., v) for v in pre]
    y = [math.fsum([p[160 + j]] + [h[i] * p[128 + j * 8 + i] for i in range(8)]) for j in range(4)]
    return {"normalized": z, "pre_activation": pre, "hidden": h, "logits": y, "class_id": argmax(y)}


def extract_features(samples, rr_current, rr_previous):
    """Binary64 version of all 12 formulas on an ALREADY resampled window."""
    x = finite(samples)
    rr, previous = finite([rr_current, rr_previous])
    if len(x) < 2 or rr <= 0 or previous <= 0:
        raise ValueError("need >=2 samples and positive RR values in seconds")
    n, half = len(x), len(x) // 2
    rms = math.sqrt(math.fsum(v * v for v in x) / n)
    mean = math.fsum(x) / n
    var = math.fsum((v - mean) ** 2 for v in x) / n
    peak = max(abs(v) for v in x)
    sign = lambda v: (v > 0) - (v < 0)
    zc = sum(sign(x[i]) != sign(x[i - 1]) for i in range(1, n)) / n
    r1 = math.sqrt(math.fsum(v * v for v in x[:half]) / half)
    r2 = math.sqrt(math.fsum(v * v for v in x[half:]) / (n - half))
    return list(finite([rms, var, peak, zc, max(x) - min(x), min(15., peak / (rms + 1e-9)),
                        r1 / (r2 + 1e-9), max(x), rr, previous, rr / (previous + 1e-9), rr - previous]))


def label_from_rule(symbol, hr, rr_current, rr_previous):
    if symbol in ("V", "F", "L", "R", "E", "A", "a", "J", "S"):
        return 3
    if rr_previous > 0 and abs(rr_current - rr_previous) / rr_previous > .20:
        return 3
    return 2 if hr < 60 else 1 if hr > 100 else 0


def resample_500_to_347(samples):
    """Independent real Fourier truncation, matching the intended SciPy operation.

    Exactly even500 -> odd347; no Nyquist bin survives. Binary64 DFT, no claim
    of float32 SciPy bit identity. Effective grid spacing is 500/(360*347) sec.
    """
    x = finite(samples)
    if len(x) != 500:
        raise ValueError("expected exactly 500 original samples")
    spectrum = []
    for k in range(174):
        re = math.fsum(x[t] * math.cos(2 * math.pi * k * t / 500) for t in range(500))
        im = -math.fsum(x[t] * math.sin(2 * math.pi * k * t / 500) for t in range(500))
        spectrum.append((re, im))
    return [(spectrum[0][0] + 2 * math.fsum(
        spectrum[k][0] * math.cos(2 * math.pi * k * t / 347)
        - spectrum[k][1] * math.sin(2 * math.pi * k * t / 347)
        for k in range(1, 174))) / 500 for t in range(347)]
