# ECG specification — Phase 0

Audit date: 2026-10-16, Asia/Saigon (client date). This is a baseline-derived specification draft, not approval of a working classifier. Diagnostic results use PASS, FAIL, or NOT RUN; unresolved decisions are explicitly marked UNDECIDED.

## Authority and scope

- Training authority: `../AI_FSM_ECG`, commit `7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d`, read-only.
- Integration source inspected: branch `ECG`, commit `983f803b3e3d815a411c46da7ae66006a9d5af03`.
- Original RTL baseline/main: `9e33a48dab0d5d517ac8adaf4000dca9f8342cda`. The two subsequent commits add instructions/plan only.
- Product: single-lead prerecorded ECG; offline Python training, FPGA inference; one class ID per accepted inference transaction. No simultaneous multichannel input or medical-validation claim.
- Stage A is feature-vector replay. Stage B adds ECG samples, windows and features. If annotation markers/RR are supplied, Stage B is explicitly oracle-assisted. Independent streaming R-peak detection is not implemented or validated.
- Phase 0 adds documentation only. [baseline_audit.md](baseline_audit.md) records evidence; [interface_contract.md](interface_contract.md) distinguishes current ports from proposed semantics.

## Source behavior: dataset and preprocessing

Source: `../AI_FSM_ECG/create_dataset.py:11-23,123-186`.

| Item | Actual reference behavior | Baseline RTL comparison | Result |
|---|---|---|---|
| Input files | `E:/code/archive/*_ekg.csv` plus `<patient_id>_annotations_1.csv` | No CSV/raw replay adapter | FAIL — absent integration path |
| Lead selection | First column containing `MLII`; else first containing `V5`; else `df_ekg.columns[1]` | 8-bit digital parallel input | FAIL — no calibrated mapping |
| Original sample rate | Script assumes 360 Hz; no metadata validation | Top comments assume 100 MHz clock and 250 Hz sampling | FAIL — incompatible acquisition contract |
| Window | Slice `[idx-250:idx+250]`, 500 samples, centered on a filtered annotation index | 512-sample banks, no beat marker | FAIL |
| Resampling | `scipy.signal.resample(win_360, int(500*250/360))`, exactly 347 samples | No resampler | FAIL |
| RR current | Difference between adjacent filtered annotation indices divided by 360, in seconds | Threshold/local-decrease detector during buffer scan, output in scan sample counts | FAIL |
| RR previous | Initialize to 0.8 seconds per record; update only after an accepted window | Initially zero; history and timer do not match accepted-window semantics | FAIL |
| Boundary policy | Skip nonpositive RR and windows outside the signal; iterate `i=1..len(valid_beats)-2` | No equivalent acceptance policy | FAIL |
| Upstream filtering, gain, offset, units | Not established by supplied files | No verified adapter | NOT RUN — source provenance unavailable |

The comment mentions V2, but the executable lead-selection code has no explicit V2 preference. The script casts the selected column to `float32`; it does not implement baseline removal, bandpass/notch filtering, amplitude normalization, or a raw integer-to-physical-unit conversion. This does not establish what preprocessing happened before the CSV was produced. Do not assume mV, ADC codes, MIT-BIH gain, or a dataset version from the path or comments.

The source window spans approximately `500/360 = 1.388889 s`, including approximately 0.694 s of samples after the annotation. The script calls the output 250 Hz, but 347 samples over the same nominal duration imply 249.84 Hz. Preserve the exact 500-to-347 per-window operation for parity; replaying arbitrary continuous samples at exactly 250 Hz is not automatically equivalent. No conversion to a 500-at-250-Hz window, 512 samples, or fixed 50% overlap is authorized.

Annotation rows are filtered without sorting or deduplication. `rr_current` uses the previous filtered row even if that previous row did not produce an accepted window; `rr_previous` tracks the last accepted window. This distinction must be retained in a compatibility reference.

## All 12 features: order, formulas and units

Let `x` be the resampled 347-element window, `N=347`, `H=floor(N/2)=173`, `eps=1e-9`, `r=rr_current`, `p=rr_previous`. Let `A` denote the unknown amplitude unit inherited from the source CSV. Population variance uses `ddof=0`. Half windows contain 173 and 174 samples respectively, each with its own mean-square denominator.

The comparison below is a source-formula audit. PASS in a row only means that formula is present; it does not prove correct samples, hardware scaling or runtime results.

| Index/name | Authoritative Python formula | Unit | Current `feature/feature_extraction.v` | Result |
|---|---|---|---|---|
| 0 `f_rms` | `sqrt(mean(x**2))` | A | Assigns `sum_square[31:0] >> 9`; no square root; reads old `rms_calc` in the same clock | FAIL |
| 1 `f_var` | `mean((x-mean(x))**2)` | A² | Q12-like `sum_square*8 - ((sum*8)^2 >>12)` is hardcoded for 512; outputs old `var_calc[15:0]` | FAIL |
| 2 `f_peak` | `max(abs(x))` | A | Signed maximum, identical to `f_max`, not absolute peak | FAIL |
| 3 `f_zc` | `count(diff(sign(x)) != 0)/N` | dimensionless | Sign-bit transition count without division by N; transitions involving exact zero differ | FAIL |
| 4 `f_ptp` | `max(x)-min(x)` | A | Sign-extended max minus min | PASS — formula only |
| 5 `f_crest` | `clip(f_peak/(f_rms+eps),0,15)` | dimensionless | Signed peak divided by old mean-square-like result; no epsilon/clip-to-15 parity | FAIL |
| 6 `f_half_ratio` | `sqrt(mean(x[:H]**2))/(sqrt(mean(x[H:]**2))+eps)` | dimensionless | Positive/nonnegative sample counter shifted by 3; unsigned comparison makes the predicate true for all 8-bit values | FAIL |
| 7 `f_max` | `max(x)` | A | Signed maximum | PASS — formula only |
| 8 `f_rr` | `r` | seconds | Scan timer count; no conversion to seconds | FAIL |
| 9 `f_rr_prev` | `p` | seconds | Previous detected scan timer count | FAIL |
| 10 `f_rr_ratio` | `r/(p+eps)` | dimensionless | Integer count ratio with shifted numerator; substitutes 1 when previous count is zero | FAIL |
| 11 `f_rr_diff` | `r-p` | seconds | Difference of timer counts | FAIL |

The feature engine's parameters do not make the arithmetic generic: sign extensions and extrema are fixed at 8 bits; normalization uses shifts for 512 even when testbenches set `NUM_SAMPLES=8`. `sample_delayed`, `mean_val`, `var_calc` and `rms_calc` are not reset. A later unconditional `rr_timer <= rr_timer + 1` overrides the peak-detection reset in the same always block. Feature-valid therefore cannot be treated as evidence of valid ECG features.

## Label semantics

Source: `create_dataset.py:21-23,95-112`. Classification output is exactly `0=Normal`, `1=Fast`, `2=Slow`, `3=Abnormal`, with the following ordered rules:

1. Symbol in `A,a,J,S,V,F,L,R,E` gives class 3.
2. Otherwise, if `p>0` and `abs(r-p)/p > 0.20`, give class 3.
3. Otherwise, `hr=60/r`: `hr<60` gives class 2; `hr>100` gives class 1; all remaining cases give class 0. Exact thresholds 60 and 100 belong to class 0 when earlier rules do not apply.

The accepted annotation allowlist is `N,L,R,A,a,J,S,V,F,[,!,e,j,E,/,f,x,Q,|,]`. Tokens outside the explicit abnormal sets fall through to RR/HR rules; they are not automatically abnormal. Mapping these CSV tokens to validated beat annotations and deciding which tokens should be allowed remains UNDECIDED. Current labels are code-specific labels, not validated medical diagnoses. Changing this policy requires a versioned dataset/model decision.

| Diagnostic | Result | Evidence/limit |
|---|---|---|
| Label ID order in Python and both MLP RTL modules | PASS | Source uses IDs 0,1,2,3 in the same order |
| Four-class coverage of supplied `label.txt` | FAIL | 500 labels: 490 class 0, 0 class 1, 0 class 2, 10 class 3 |
| Full dataset distribution and annotation validity | NOT RUN | Dataset and annotation CSVs are not in either repository |
| Accuracy of the supplied checkpoint | NOT RUN | No reproduced held-out dataset, provenance or evaluation |

## Training and inference math

`train_2.py` selects every `f_` column in CSV order, then performs stratified row-level splits 70/15/15 with `random_state=42`. It does not group by `patient_id`. Patient separation is therefore not enforced; actual overlap/leakage cannot be quantified without the dataset. The scaler is fitted on training rows only and applied unchanged to validation/test.

Model math:

```text
z[i] = (feature[i] - mean[i]) / scale[i], i=0..11
h[j] = max(0, sum_i(W1[j,i] * z[i]) + b1[j]), j=0..7
logit[k] = sum_j(W2[k,j] * h[j]) + b2[k], k=0..3
class_id = first index attaining the largest logit
```

No softmax is required for argmax. Training uses batch size 64, up to 250 epochs, Adam at 0.003 with weight decay `1e-4`, cross-entropy class weights `[1,1.5,1.5,3]`, and ReduceLROnPlateau on validation accuracy. Torch/NumPy initialization and shuffle seeds are not fixed by the script. Early-stop variables exist but are unused. The best-accuracy block never saves a checkpoint; evaluation loads an already existing `mlp_fpga_best.pth`. Re-running training also overwrites the scaler before that load. Consequently the current script does not reproduce or establish the provenance of the supplied checkpoint/scaler pair.

## Current numeric package and ROM map

`convert_to_hex.py` uses `int(value*4096)` (truncate toward zero), clamps to signed 16-bit `[-32768,32767]`, then stores two's-complement hex. Its Q4.12 convention includes the sign in four integer bits: range `[-8,7.999755859375]`, step `1/4096`.

| Word addresses | Count | Meaning/order |
|---|---:|---|
| 0–11 | 12 | Means in feature order |
| 12–23 | 12 | `1/scale` in feature order |
| 24–119 | 96 | FC1, output-neuron major: `24 + 12*j + i` |
| 120–127 | 8 | FC1 biases, neuron order |
| 128–159 | 32 | FC2, output-neuron major: `128 + 8*k + j` |
| 160–163 | 4 | FC2 biases, class order |

| Artifact diagnostic | Result |
|---|---|
| `weight.hex`: 164 words; first 24 equal quantized CSV means/reciprocals | PASS |
| Remaining 140 words equal checkpoint float32 storages quantized in W1,b1,W2,b2 order | PASS |
| `weight.mi` equals `weight.hex` | PASS |
| Embedded Gowin INIT_RAM words equal HEX when each 256-bit block is decoded low 16-bit word first | PASS — serialization only, not physical ROM timing |
| Package represents every scaler reciprocal without clipping | FAIL — address 15, feature 3: `57.77128774964532` becomes `0x7FFF = 7.999755859375` |
| `first_500.txt` has 500×12 four-digit hex values and 500 labels | PASS — shape only |
| Meaning, feature order, normalization state and generation lineage of those 500 vectors | NOT RUN — no verified conversion chain |
| Float/fixed-point intermediate parity and classification agreement | NOT RUN |

The data-shape/export checks used Python 3.12.10 standard-library ZIP/float32 decoding and text parsing, without executing training scripts or loading arbitrary pickle objects. The serialized archive is little-endian and has float storages of 96, 8, 32 and 4 elements. Matching an exporter that clamps values is not approval of a valid inference package. Crest is allowed up to 15 by the reference, also beyond signed Q4.12; actual feature clipping frequency cannot be measured with the missing dataset.

The active `ai_classifier` has 16-bit input/parameter arrays, 32-bit normalized/hidden/output arrays and a 48-bit MAC temporary. It omits the normalization `>>12`, then adds Q12 biases to differently scaled accumulations. ReLU compares a signed value with unsigned `32'd0`. The training repository's `hr_top` does shift normalization by 12 but uses a 32-bit temporary for wider products and vendor-specific ROM timing. Neither RTL implementation is a bit-accurate reference just because the Python repository is authoritative.

### Embedded baseline model manifest

The requested three-document deliverable contains the manifest here. The plan's separate `docs/model_manifest.json` remains a proposed Phase 1 artifact; no fourth output file or regenerated model is created in Phase 0.

| File in `AI_FSM_ECG` | Bytes | SHA-256 |
|---|---:|---|
| `mlp_fpga_best.pth` | 3033 | `a085cdf6c7a4edbea427f6e5afc178fe4d2583cc42136c5a1c021a9044624079` |
| `scaler_params_fpga.csv` | 491 | `ddc9b4f1d15f234bba9098bd41b81b25488e58000372b87dc2e08ed6af6b043c` |
| `weight.hex` | 984 | `58900c36b13a98e5cf1d9f476041acac272df1ac521617274c42ff968491f6ad` |
| `weight.mi` | 1518 | `4b6ebe0eade698e7d9e2385b8fcf13f007d817c4096fc429a8c77a3fa1a9c841` |
| `first_500.txt` | 36000 | `6f2ab0ad534c43ef8b661171a7565c8b504388d1e14b44b404a722ee3d190722` |
| `label.txt` | 1500 | `f9628d14c336206eedf425c73a5d376df8553f3e6e2b3e66c38934daba23becc` |

Dataset identity/hash, upstream preprocessing, library versions used to train, training run seed, checkpoint selection history and measured accuracy: **unknown**.

## Unresolved decisions and acceptance gates

| ID | Decision / missing evidence | Proposed direction, not implemented | Verification result |
|---|---|---|---|
| U1 | Dataset revision, CSV amplitude unit, lead provenance, gain/offset, earlier filters | Obtain original CSV/annotation metadata and checksum; do not infer mV | NOT RUN |
| U2 | Annotation allowlist and RR event semantics | Preserve current code for compatibility; review tokens before any relabeling | NOT RUN |
| U3 | First raw-sample demo: pre-windowed replay, oracle-assisted event stream or online detector | First use the exact 347-sample Python windows plus matching RR metadata; describe as oracle-assisted | NOT RUN — UNDECIDED |
| U4 | Signed-16 sample encoding and feature/scaler/product/accumulator formats | Storage width is not ADC resolution or automatically Q4.12; choose widths from ranges and error budget | NOT RUN — UNDECIDED |
| U5 | Rounding, saturation, epsilon approximation and per-layer tolerances | Require explicit policy and bit-exact agreement with an independent fixed-point reference | NOT RUN — UNDECIDED |
| U6 | Canonical MLP implementation | Recommend a vendor-neutral core in integration repository informed by both existing cores; neither selected as proven | NOT RUN — UNDECIDED |
| U7 | Ready/valid naming, buffering, busy rejection, reset-abort and IRQ acknowledgment | Proposed semantics in interface contract require review before implementation | NOT RUN — UNDECIDED |
| U8 | Float-to-fixed permitted classification degradation | Report measured differences first; do not invent an accuracy target | NOT RUN — UNDECIDED |
| U9 | Board clock, pin/UART route and installed FPGA part | Plan requests 50 MHz and `xc7z020clg484-1`; current RTL assumes 100 MHz. Verify installed part and actual clocking in Phase 5 | NOT RUN |

Phase 0 documentation is available for review. Specification sign-off is NOT RUN; functional correctness gate is FAIL because confirmed defects remain. No acceptance of clipping, changed windows, weakened tests, or an online R-peak algorithm is implied.
