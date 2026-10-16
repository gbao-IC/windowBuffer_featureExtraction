# ECG Integration Implementation Plan

**Scope:** gbao-IC/windowBuffer_featureExtraction branch `ECG`. Training reference: sibling `AI_FSM_ECG` (read-only). All baseline failures must be reproduced before declaring repaired.

## Phase 0 - Baseline and specification (no functional edits)
- Capture branch/commit, tool versions, file inventory, and lint/elaboration errors.
- Compare `create_dataset.py`, `train_2.py`, `convert_to_hex.py`, `hr_top.v`, existing `top/`, `feature/`, `window/`, and tests.
- Write `docs/ecg_spec.md`, `docs/model_manifest.json`, and an interface map with **explicit undecided fields** rather than guessing.
- Decide: beat-centered annotation-assisted demo versus independent online detection; rate/window contract; 4-label interpretation; feature units; numeric format; selected MLP RTL.
- Gate: reviewed spec + baseline report. No claim of functional correctness.

## Phase 1 - Valid model and independent references
- Check training train/validation/test split leakage by patient, checkpoint save/load provenance, unsupported annotation tokens, label distribution and 4-class coverage.
- Audit quantization range: existing Q4.12 clamps reciprocal scaler values above ~8; redesign scaler representation and regenerate synchronized model artifacts as needed in a separate approved training branch.
- Generate reproducible float and bit-exact fixed-point golden intermediate vectors for samples/window, all 12 features, normalized vector, 8 hidden values, 4 logits and predicted class, plus hashes.
- Gate: training provenance recorded; fixed-point versus float loss quantified; representative vectors in each of 4 classes.

## Phase 2 - Standalone inference core
- Implement vendor-neutral dual-port read ROM wrapper in RTL for 164 model words, equivalent address ordering and documented synchronous read latency; Vivado inference or BMG variant separately.
- Choose a single authoritative MLP module, correct signed MAC/quantization/rounding/saturation, layer control and start/ready/valid/done.
- Test all intermediate layers against golden fixed-point, including difficult edge cases and repeated transactions.
- Gate: lint and RTL simulation pass; all selected fixed-point vectors match specified tolerance; documented resource estimate.

## Phase 3 - ECG feature engine and window
- Replace PPG-only 8-bit input assumptions with signed 16-bit sample contracts and proper address widths.
- Implement beat-aligned or sliding window **only as approved in specification**, define marker/RR sourcing; fix read latency, last-sample, bank conflicts/overlap.
- Match Python definitions precisely: RMS sqrt(mean(x^2)), variance, abs peak, normalized zero-crossing rate, peak-to-peak, crest, half-window RMS ratio, max, RR current/previous/ratio/diff.
- Gate: sample ordering and 12 features validated against golden; reset, overflow, back-to-back and annotated beat marker tests.

## Phase 4 - Top-level integration, FSM, interfaces
- Redesign master sequencer around valid/ready/done rather than fixed cycle assumptions; preserve internal MLP FSM. Implement overflow/backpressure policy.
- Fix APB ports/write/read semantics, clock/reset, IRQ, UART and formatting. Add ECG replay source and optional XADC adapter later.
- Integration test: prerecorded ECG -> buffer -> features -> MLP -> class register/UART; verify 0..3 and no duplicate/missing transaction.
- Gate: self-checking end-to-end regression with timeouts; documented contract for UART bytes; no unresolved critical synthesis/lint errors.

## Phase 5 - UVM and hardware
- Start with self-checking SystemVerilog directed tests and assertions; add UVM agent, monitor, scoreboard, sequences and coverage for FSM and integration as supported by installed simulator. Check exact XSim/UVM edition/version via a smoke test first; do not infer capability from an extension.
- Record feature, FSM and integration coverage separately with exclusions.
- Create ZC702 Vivado project for `xc7z020clg484-1`, synthesize only synthesizable RTL+ROM initialization, configure 50 MHz working clock through clocking hardware as needed, add board-specific XDC and output path.
- Prove feature replay first, then raw ECG replay; measure timing WNS/TNS, LUT/FF/DSP/BRAM, actual sample throughput, class outputs, and ILA/UART evidence.
- Gate: artifacts with exact git SHA, tool version, logs, bitstream and waveforms. No live-human acquisition claim without proper analog safety validation.

## Agent work pattern
1. Agent proposes files/tests and explains boundary conditions.
2. Agent edits ONLY approved phase and runs tests, saving reproducible logs.
3. Reviewer checks diff and reruns tests independently.
4. Human reviews before commit/push/merge.
5. One commit per coherent change, not one monolithic mass refactor.

## Phase 0 starting prompt
Read AGENTS.md and both repository trees. Do not edit source RTL in this phase. Create a compact baseline report and draft ECG specification, explicitly enumerating contradictions in sampling/window, label definition, feature formulas, Q-format, ROM, and four-class test coverage. Do not fabricate results or change the training repo.
