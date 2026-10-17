# ECG Phase 0 baseline audit

Audit date: 2026-10-16, Asia/Saigon (client date). Scope: immutable training reference and existing integration RTL/tests, plus three new documentation files. No source repair, retraining, model regeneration, deletion, commit, push or merge is part of this audit.

Read in full before execution: `AGENTS.md` and `docs/ECG_INTEGRATION_PLAN.md`. Source facts and unresolved decisions are separated below. PASS applies only to the named diagnostic; compilation/elaboration PASS does not imply functional, synthesis or hardware correctness.

## Git baseline

| Repository | Branch / HEAD | Remotes (fetch and push) | Initial working tree | Result |
|---|---|---|---|---|
| `AI_FSM_ECG` | `main`, `7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d` | `origin https://github.com/gbao-IC/AI_FSM_ECG.git` | Clean, including untracked-file inspection | PASS |
| `windowBuffer_featureExtraction` | `ECG`, `983f803b3e3d815a411c46da7ae66006a9d5af03` | `origin https://github.com/gbao-IC/windowBuffer_featureExtraction.git` | Clean, including untracked-file inspection | PASS |

Training `main=origin/main=HEAD` at the reference SHA. RTL `main=origin/main=9e33a48dab0d5d517ac8adaf4000dca9f8342cda`; `ECG=origin/ECG=983f803b3e3d815a411c46da7ae66006a9d5af03`. The integration branch is two commits ahead of main: `4cbc06d` adds AGENTS.md; `983f803` adds the integration plan. `git diff --name-status main..ECG` lists only those two documents. Both local main reflogs contain only the clone entry. Original local main preservation: PASS. Remote-tracking refs are local observations; a fresh network query is NOT RUN in this phase.

Commands run in each repository:

```powershell
git --no-optional-locks status --short --branch --untracked-files=all
git branch -vv
git remote -v
git show-ref
git reflog show main --date=iso
rg --files --hidden -g '!**/.git/**'
```

Additional RTL commands: `git diff --name-status main..ECG` and `git log -3 --oneline`. A SHA-256 snapshot of all 67 pre-existing non-.git files was taken before source diagnostics for final preservation checking.

## Architecture inventory

### Training reference — all 15 files

| Files | Role / dependencies / current limits |
|---|---|
| `create_dataset.py` | Read per-record ECG/annotation CSVs, select one lead, annotation-centered 500@360 windows, SciPy resample to 347, 12 features and four-rule label policy |
| `train_2.py` | pandas/NumPy/PyTorch/sklearn; row split, StandardScaler, MLP 12–8–4, weighted loss/Adam/scheduler, matplotlib/seaborn evaluation; missing checkpoint save |
| `convert_to_hex.py` | Read checkpoint+scaler; flatten W1,b1,W2,b2; clamp/truncate signed Q4.12; emit 164 words |
| `feature_extract_column.py` | Read missing `features.xlsx`, select positional columns 15:27 from first 500 rows, skip NaNs, write decimal text; not a verified producer of supplied HEX vectors |
| `mlp_fpga_best.pth`, `scaler_params_fpga.csv` | Supplied parameter artifacts; architecture and scaler shape checked; training-run provenance unknown |
| `weight.hex`, `weight.mi` | HEX and Gowin address/hex initialization; both match, with known clipping |
| `first_500.txt`, `label.txt` | 6000 HEX feature-like values and 500 labels; two represented classes; raw-window/source-row lineage unknown |
| `hr_top.v` | Alternative feature-input inference FSM, captured vector, normalization/MAC/ReLU/argmax, Gowin dual-port ROM; not used by integration top |
| `gowin_dpb.v` | GW5A-LV25 generated DPB wrapper and embedded constants; vendor notices retained |
| `prim_sim.v` | DPB simulation primitive, 16-bit read/write behavior and hierarchical `GSR.GSRO` reference; not a Xilinx synthesis implementation |
| `GSR.v` | Minimal global reset simulation module; no supplied training testbench instantiates the required complete hierarchy |
| `README.md` | External spreadsheet link and references to testbenches absent from current tree |

Dataset CSV, raw ECG/annotation CSVs, spreadsheet, dependency lockfile and the referenced training testbench are absent from the repository inventory. Recreating training/evaluation: NOT RUN. No external dataset or spreadsheet was guessed or imported.

### Integration repository — all 52 pre-existing files

| Files | Role / boundary |
|---|---|
| `adc/adc_interface.v` | 8-bit sample latch, 16-bit rate timer, one pending sample, overflow |
| `window/window_buffer.v` | Two 512×8 banks, registered read address, bank-ready pulse; claimed overlap not implemented |
| `feature/feature_extraction.v` | 8-bit input, twelve signed-16 outputs; accumulation/calculation FSM with incompatible formulas |
| `ai/ai_classifier.v` | 12–8–4 inference with placeholder weights; separate internal layer FSM |
| `ai/mlp_weights_rom.v` | Standalone 164×16 synchronous-read ROM; not connected to classifier |
| `control/control_fsm.v` | Ten-state master, timed layer-like states; no window-ready/MLP-done/UART-done inputs |
| `apb/apb_slave_if.v` | Seven CSR offsets; internal, unexported IRQ |
| `uart/uart_tx.v` | Configurable 8N1 transmitter; no receiver |
| `top/top_ppg_classifier.v` | Instantiates seven processing/control modules, but not the ROM; exposes APB/ADC/UART/IRQ/LEDs |
| `synthesis/run_synth.tcl` | Gowin GW5A target, `rtl/...` paths absent relative to repository root; no ZC702 project/XDC |
| `tb/tb_apb_slave_if.sv`, `tb/tb_adc_interface.sv` | CSR/data-forwarding directed tests; no complete protocol or multi-writer proof |
| `tb/tb_window_buffer.sv`, `tb/tb_window_simple.sv` | Window-ready/reset/read exercises; no complete overlap or first/last-sample scoreboard |
| `tb/tb_feature_extraction.sv`, `tb/tb_feature_simple.sv` | Eight-sample patterns, peak/PTP/zero checks and waveform inspection; no independent 12-feature ECG model |
| `tb/tb_control_fsm.sv` | Exercises entry to LOAD/NORM only; missing connections to other control outputs |
| `tb/tb_uart_tx.sv` | Sends 0x55, waits for done; no bit-level receive scoreboard |
| `tb/tb_ai_classifier.sv` | Synthetic feature vectors; waits for done and prints PASS without golden label/layer comparison |
| `tb/tb_top_ppg_classifier.sv` | PPG-like offset sine input, APB exercises, timeout; no ECG ground truth |
| `sim/tb_top.sv` | Alternative testbench with the same module name as tb top; compile separately; real-to-signed conversion elaboration error |
| `tb/Makefile` | Icarus targets; top target omits top RTL from its source list |
| `tb/run_all.bat`, `tb/run_all.sh` | Batch hardcodes missing `E:\iverilog`; executes six despite labels /8. `.sh` contains Windows batch syntax |
| `tb/run_apb.bat`, `tb/run_control.bat`, `tb/run_feature.bat`, `tb/run_simple.bat`, `tb/run_simple_feature.bat`, `tb/run_uart.bat`, `tb/run_window.bat`, `tb/run_tb.bat` | Individual legacy launchers; run_tb points at absent `b_window.vvp` |
| `README.md`, `AGENTS.md`, `docs/ECG_INTEGRATION_PLAN.md` | Legacy PPG/Gowin overview, repository policy, phase gates |

Existing generated artifacts were inventoried, not executed as trusted binaries, overwritten or deleted:

```text
tb/tb_adc.vvp                 tb/tb_adc_interface.vcd
tb/tb_apb.vvp                 tb/tb_apb_slave_if.vvp
tb/tb_apb_slave_if.vcd         tb/tb_control.vvp
tb/tb_control_fsm.vcd          tb/tb_feature.vvp
tb/tb_feature_extraction.vcd   tb/tb_feature_simple.vvp
tb/tb_feature_simple.vcd       tb/tb_uart.vvp
tb/tb_uart_tx.vcd              tb/tb_window.vvp
tb/tb_window_buffer.vcd        tb/tb_window_simple.vvp
tb/tb_window_simple.vcd
```

Existing generated-artifact freshness and equivalence to current source: NOT RUN. README latency/resource estimates are not measured results.

## Tools and execution

Discovery checked PATH and executable names under `C:\msys64`, `C:\Xilinx`, `C:\MentorGraphics`, `C:\altera`, `C:\Gowin`, Program Files, plus the hardcoded `E:\iverilog` location. No tools were installed or upgraded.

| Tool/check | Result | Observed availability / action |
|---|---|---|
| Questa `vlog`, `vopt` | PASS | `C:\MentorGraphics\win64`; version 2024.1, Compiler 2024.02 Feb 1 2024 |
| Questa `vsim -version` | PASS | Questa Sim-64 2024.1, Simulator 2024.02 Feb 1 2024 |
| Python | PASS | 3.12.10, standard-library artifact inspection |
| Icarus `iverilog` / `vvp` | NOT RUN | Not found in inspected paths; legacy E: path absent |
| Verilator | NOT RUN | Not found in inspected paths |
| Vivado / XSim / installed ZC702 part listing | NOT RUN | Not found in inspected paths |
| Slang, Verible, Yosys; Python HDL parsers | NOT RUN | Not found in inspected paths / selected Python environment; optional cross-check tools |
| Older ModelSim Altera / Xilinx ISE / Gowin | NOT RUN | Executables found; not used as substitutes for current Questa SV diagnostics or ZC702 Vivado validation |
| Functional simulation / golden parity | NOT RUN | This run performs compile/lint and elaboration only; no simulation time was advanced |
| Synthesis, timing, UVM, bitstream, board execution | NOT RUN | Outside Phase 0 and no verified Vivado installation |

Missing-tool installation steps, not executed:

- Icarus: open MSYS2 UCRT64, run `pacman -S --needed mingw-w64-ucrt-x86_64-iverilog`, then use `C:\msys64\ucrt64\bin\iverilog.exe` and `vvp.exe` or add that directory to PATH. [Official MSYS2 package](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-iverilog).
- Verilator: in an available Ubuntu/WSL environment, run `sudo apt-get update` followed by `sudo apt-get install verilator`; verify `verilator --version`. WSL installation itself is not assumed. [Official installation guide](https://verilator.org/guide/latest/install.html).
- Vivado/XSim: use AMD Unified Installer, select Vivado and Zynq-7000 device support, initialize the installed version's environment, verify `vivado -version` and Tcl `get_parts xc7z020clg484-1`. No release, license entitlement or installed part support is assumed. [AMD installer information](https://www.amd.com/en/support/adaptive-socs-and-fpgas/installer-info-general.html).
- Optional Slang: extract the Windows release, add `slang.exe` to PATH and verify `slang --version`; alternatively run `python -m pip install pyslang` in a dedicated environment. [Official Slang instructions](https://www.sv-lang.com/user-manual.html).
- Optional Verible: extract the Windows binary release, add its bin directory to PATH and verify `verible-verilog-lint --version`. [Official installation instructions](https://chipsalliance.github.io/verible/README.html).
- Optional Yosys: install a prebuilt OSS CAD Suite for the platform and initialize its environment, then verify `yosys -V`. [Official Yosys installation instructions](https://github.com/YosysHQ/yosys/blob/main/docs/source/getting_started/installation.rst?plain=true). PyVerilog/hdlConvertor were discovery probes only; neither is required by the selected Questa flow. These optional tools are not replacements for mandatory Vivado part/build checks.

All compiler work libraries/logs were directed to `C:\Users\giado\AppData\Local\Temp\ecg-phase0-i6t27i2m`. Initial sandbox access to temp failed with `PermissionError: [Errno 13] Permission denied`; the same diagnostic work was rerun with approved elevated access. That environment failure is not an RTL failure. Temporary files are not repository deliverables and may be removed externally later; essential commands and diagnostics are preserved here.

### Reproduction procedure

From a new writable scratch directory, set `$rtl` to this repository and `$q` to the Questa bin directory. Do not use the legacy scripts that overwrite tracked VCD/VVP files.

```powershell
$rtl = 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction'
$q = 'C:\MentorGraphics\win64'
& "$q\vlog.exe" -version
& "$q\vopt.exe" -version
& "$q\vlib.exe" work
# For each source in the table below, run in table order:
& "$q\vlog.exe" -sv -lint -work work "$rtl\apb\apb_slave_if.v"
# After all nine RTL units compile, elaborate each named top separately:
& "$q\vopt.exe" -work work work.apb_slave_if -o apb_slave_if_elab
# Repeat for each tb/*.sv: compile file, then elaborate its module name.
# Compile sim/tb_top.sv last: its module name duplicates the tb top.
```

No error/warning suppression, source modification, forced nets or stub modules were used. Process success means exit code 0; warnings remain recorded. Compilation uses SystemVerilog explicitly because several `.v` files have unpacked-array ports. Each command had a 45-second process timeout; no command timed out. Elaborating leaf modules with no driven external inputs is only a structural smoke check.

### Actual result matrix

| Source / elaborated module | Compile + `-lint` | `vopt` elaboration | Notes |
|---|---|---|---|
| `apb/apb_slave_if.v` / `apb_slave_if` | PASS | PASS | 0 errors, 0 warnings |
| `adc/adc_interface.v` / `adc_interface` | PASS | PASS | 0 errors, 0 warnings |
| `window/window_buffer.v` / `window_buffer` | PASS | PASS | 0 errors, 0 warnings |
| `feature/feature_extraction.v` / `feature_extraction` | PASS | PASS | 0 errors, 0 warnings |
| `ai/ai_classifier.v` / `ai_classifier` | PASS | PASS | 0 errors, 0 warnings |
| `ai/mlp_weights_rom.v` / `mlp_weights_rom` | PASS | PASS | File initialization is not executed by elaboration |
| `control/control_fsm.v` / `control_fsm` | PASS | PASS | 0 errors, 0 warnings |
| `uart/uart_tx.v` / `uart_tx` | PASS | PASS | 0 errors, 0 warnings |
| `top/top_ppg_classifier.v` / `top_ppg_classifier` | PASS | FAIL | exit 2: missing p_irq; address width warning |
| `tb/tb_adc_interface.sv` | PASS | PASS | 1 compile and 1 elaboration warning |
| `tb/tb_ai_classifier.sv` | PASS | PASS | 1 compile and 1 elaboration warning |
| `tb/tb_apb_slave_if.sv` | PASS | PASS | 1 compile and 2 elaboration warnings |
| `tb/tb_control_fsm.sv` | PASS | PASS | 1 compile and 9 elaboration warnings |
| `tb/tb_feature_extraction.sv` | PASS | PASS | 1 compile and 1 elaboration warning |
| `tb/tb_feature_simple.sv` | PASS | PASS | 1 compile and 1 elaboration warning |
| `tb/tb_top_ppg_classifier.sv` | PASS | FAIL | exit 2: same top port error |
| `tb/tb_uart_tx.sv` | PASS | PASS | 1 compile and 1 elaboration warning |
| `tb/tb_window_buffer.sv` | PASS | PASS | 1 compile and 1 elaboration warning |
| `tb/tb_window_simple.sv` | PASS | PASS | 1 compile and 1 elaboration warning |
| `sim/tb_top.sv` / `tb_top_ppg_classifier` | PASS | FAIL | exit 12: signed conversion of real expression |

Totals: compile/lint **20 PASS**; elaboration **17 PASS, 3 FAIL**. The 20 units are nine RTL sources and eleven testbench sources. Original legacy Icarus launchers: NOT RUN because Icarus is unavailable; these commands used explicit full RTL sources instead. No claim is made that those launchers pass.

### Exact blocking diagnostics

The following messages are copied from Questa outputs; line numbers refer to the unmodified baseline. The p_irq error reports connection-list line 164, while `.p_irq(csr_irq)` itself is line 175.

```text
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\top\top_ppg_classifier.v(164): (vopt-2241) Connection width does not match width of port 'paddr'. The port definition is at: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\apb\apb_slave_if.v(12).
** Error (suppressible): C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\top\top_ppg_classifier.v(164): (vopt-2912) Port 'p_irq' not found in module 'apb_slave_if' (11th connection).
Optimization failed
Errors: 1, Warnings: 1
```

This occurs for `work.top_ppg_classifier` and `work.tb_top_ppg_classifier` compiled from `tb/` (FAIL, exit 2). For the alternative `sim/` testbench (FAIL, exit 12):

```text
** Error: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\sim\tb_top.sv(142): The signed/unsigned conversion is not allowed for a real expression.
Optimization failed
Errors: 1, Warnings: 0
```

This frontend error prevents reaching the same top-level port check through the alternative testbench. No claim of further clean elaboration is implied.

Other observed diagnostics: `vlog-2623` / `vopt-2623` name each testbench scope passed to `$dumpvars` as an undefined variable. Locations: ADC 226, AI 291, APB 255, control 33, feature 168, feature_simple 43, top 328, UART 32, window 225, window_simple 47, sim top 223. APB TB line 49 also gets `vopt-2241` for address width. Control TB line 16 gets `vopt-2685` (16 ports expected, 9 found) and `vopt-2718` for `next_state_debug`, `read_addr`, `uart_send`, `mlp_valid`, `mlp_start`, `feature_read_en`, `feature_start`. These warnings were not suppressed. Runtime dump behavior is NOT RUN, so the scope warnings are not treated as proof of a runtime functional failure.

Questa also printed a notice that `MGLS_LICENSE_FILE` / `LM_LICENSE_FILE` support will be discontinued starting with 2025.1 and recommends `SALT_LICENSE_SERVER`. Licensing succeeded in this run; no license configuration was changed.

## Confirmed defects, with evidence class

FAIL here means an identified baseline contract violation. A source-confirmed defect is not mislabeled as a simulator-reproduced failure.

| ID | Result | Evidence class / location | Defect and consequence |
|---|---|---|---|
| D01 | FAIL | Questa elaboration; top:164/175, APB ports | `p_irq` does not exist as an APB output; integrated top cannot elaborate |
| D02 | FAIL | Questa elaboration; sim/tb_top.sv:142 | `$signed` applied to `$sin` real-valued expression is illegal |
| D03 | FAIL | Source; top:56-59 | `clk_locked` undriven; reset release cannot be validly established |
| D04 | FAIL | Source; top:208, ADC rate timer | `16'd400000` truncates to 6784; timer period is divisor+1. At nominal 100 MHz the tick is about 14.738 kHz, not 250 Hz; delivered data also depends on pending valid |
| D05 | FAIL | Source; adc/adc_interface.v | `data_pending` and `overflow_flag` written from two clocked blocks; CDC/acquisition mode not implemented |
| D06 | FAIL | Source; window:72-84 | Full-window branch switches bank without writing the last sample or counting it |
| D07 | FAIL | Source; window parameters/addressing | OVERLAP unused; banks are nonoverlapping; bank address concatenation assumes 512 and is unsafe if changed to 347 without address redesign |
| D08 | FAIL | Source; control:99 and entire module; top:224 | `feature_read_en` never set to 1; window read address stays at its reset value |
| D09 | FAIL | Source; feature:230-241 | `f_var` and `f_rms` take previous temporary values due to nonblocking assignment ordering; temporaries not reset |
| D10 | FAIL | Source; feature:157-258 | Wrong RMS/absolute peak/ZC/half ratio/RR semantics; fixed 8-bit/512 assumptions. Full per-feature comparison in ecg_spec.md |
| D11 | FAIL | Source; feature:184-193 | Unconditional timer increment overrides detected-peak reset; history does not implement annotation RR |
| D12 | FAIL | Source; feature reset/overflow blocks | `overflow` has multiple procedural writers; check covers only high sum-square bits, not downstream narrowing |
| D13 | FAIL | Source; ai_classifier:94-159; top hierarchy | Zero weights/biases, identity scaler placeholders; undriven/incomplete loader; separate ROM not connected |
| D14 | FAIL | Source; mlp_weights_rom:37; workspace inventory | Hardcoded `../AI_FSM_ECG-main/AI_FSM_ECG-main/weight.hex` does not identify actual artifact from normal repo/tb working directories |
| D15 | FAIL | Source; ai_classifier:220-276 | Missing normalization right shift; inconsistent bias binary point; unsigned-zero ReLU comparison can retain negative values |
| D16 | FAIL | Source; ai_classifier control/reset | LOAD does not snapshot features; class code not reset; overflow never asserted |
| D17 | FAIL | Source; control_fsm; top:299 | Master has no window-ready/MLP-done/UART-busy inputs; starts early, holds MLP start high, predicts completion via unrelated counters; next_state not reset |
| D18 | FAIL | Source; APB, top | Setup-phase writes, missing exported handshake, pulse-only/unexported IRQ, inconsistent CONFIG reset/readback, soft reset only reaches window |
| D19 | FAIL | Python artifact check | Reciprocal scaler for ZC clips from 57.77128774964532 to 7.999755859375 at ROM address 15 |
| D20 | FAIL | Source; train_2.py:160-180 | Best checkpoint never saved; evaluation loads an existing artifact after newly fitting/saving scaler |
| D21 | FAIL | Python text check | Supplied 500 labels lack classes 1 and 2; cannot support four-class acceptance |
| D22 | FAIL | Source; Makefile/run scripts | Top source omitted from Makefile; `.sh` is batch; `run_all.bat` omits AI/top and hardcodes absent E: tool; run_tb references absent file |
| D23 | FAIL | Source; feature TB, AI TB, top TB | Feature TB expects `f_peak=-1` for all -1, contradicting absolute peak; AI unconditionally prints PASS after done; top has no golden check and even a knownness-sensitive weak completion condition |
| D24 | FAIL | Source; synthesis script/inventory | Gowin target and `rtl/...` layout assumptions do not form a ZC702 Vivado build; README latency/resources are unverified |

Patient-group leakage is a risk confirmed in split design, not a measured dataset-overlap result. Unknown sensor units, annotation validity, model provenance, replacement Q-formats, numerical tolerances and canonical MLP selection are **unresolved decisions/evidence**, not invented measurements. Their validation is NOT RUN; see U1–U9 in ecg_spec.md.

## Reproducing the artifact audit without training

Run the following from `AI_FSM_ECG` using `python -B -` with the code supplied through stdin (PowerShell here-string). It only reads files and prints diagnostics. It does not import training modules or unpickle executable objects. These are the same calculations used for the recorded artifact results and hashes in ecg_spec.md.

```python
from pathlib import Path
import collections, csv, hashlib, re, struct, zipfile

p = Path.cwd()
words = [int(v, 16) for v in (p / 'weight.hex').read_text().split()]
rows = list(csv.DictReader((p / 'scaler_params_fpga.csv').open()))
quant = lambda v: max(-32768, min(32767, int(v * 4096))) & 65535
scaler = [quant(float(r['mean'])) for r in rows]
scaler += [quant(1 / float(r['scale'])) for r in rows]
print('PASS' if len(words) == 164 and words[:24] == scaler else 'FAIL',
      'HEX length and scaler serialization')
with zipfile.ZipFile(p / 'mlp_fpga_best.pth') as z:
    order = z.read(next(n for n in z.namelist() if n.endswith('/byteorder')))
    assert order == b'little'
    values = []
    for i, count in enumerate((96, 8, 32, 4)):
        raw = z.read(next(n for n in z.namelist() if n.endswith('/data/' + str(i))))
        assert len(raw) == 4 * count
        values.extend(struct.unpack('<' + 'f' * count, raw))
print('PASS' if [quant(v) for v in values] == words[24:] else 'FAIL',
      'checkpoint storages W1,b1,W2,b2 versus HEX')
mi = [int(line.split(':')[1], 16)
      for line in (p / 'weight.mi').read_text().splitlines() if ':' in line]
print('PASS' if mi == words else 'FAIL', 'MI versus HEX')
packed = []
for _, hexblock in re.findall(r"INIT_RAM_([0-9A-F]{2}) = 256'h([0-9A-Fa-f]+)",
                             (p / 'gowin_dpb.v').read_text()):
    packed.extend((int(hexblock, 16) >> (16*i)) & 65535 for i in range(16))
print('PASS' if packed[:164] == words else 'FAIL', 'embedded ROM serialization')
clipped = [(i, 1/float(r['scale']), words[12+i]/4096)
           for i, r in enumerate(rows) if 1/float(r['scale']) > 32767/4096]
print('FAIL' if clipped else 'PASS', 'reciprocal representability', clipped)
vectors = (p / 'first_500.txt').read_text().split()
labels = (p / 'label.txt').read_text().split()
valid = len(vectors) == 6000 and len(labels) == 500
valid = valid and all(re.fullmatch('[0-9A-Fa-f]{4}', v) for v in vectors)
print('PASS' if valid else 'FAIL', '500 by 12 HEX / label shape')
print('PASS' if set(labels) == {'0','1','2','3'} else 'FAIL',
      'four-class coverage', dict(collections.Counter(labels)))
for name in ('mlp_fpga_best.pth', 'scaler_params_fpga.csv', 'weight.hex',
             'weight.mi', 'first_500.txt', 'label.txt'):
    print(name, hashlib.sha256((p / name).read_bytes()).hexdigest())
```

Storage numbering is specific to this pinned checkpoint; the state's keys/order were inspected with `pickletools`, and model dimensions were read from `train_2.py`. This snippet is not a general checkpoint loader. Supplied HEX-vector shape is not validation of its numeric encoding or data lineage.

## Smallest next implementation slice

Recommend **Phase 1A: an executable model-package audit and independent numerical reference**, before RTL repair. Proposed files (not created now): `tools/audit_model.py`, independent reference/tests, and `docs/model_manifest.json`.

1. Consume training artifacts read-only; check hashes, 164-word layout, exact feature/label order, signed decoding and every saturation. Preserve the current clipping case as a failing acceptance check, not an approved clamp.
2. Trace the 500 vectors' origin/encoding before reporting accuracy. Keep synthetic numeric edge cases explicitly separate from dataset evidence; obtain representative classes 1 and 2 before a four-class gate.
3. Implement independent float and integer scaler/MLP calculations with intermediate traces. Select a wider scaler representation only after an explicit numeric decision; never silently regenerate training artifacts.
4. Exit gate: reproducible package audit, honest invalid-package detection, documented numeric policy and measured float/fixed differences. Missing data/provenance remains NOT RUN rather than a fabricated PASS.

This slice avoids coupling ROM, MAC, feature extraction, window repair and FPGA integration in one change. Phase 2 then implements the standalone feature-vector replay MLP; raw ECG/beat detection and APB/UART repair remain later phases.

## Phase 0 disposition

Documentation and available baseline diagnostics: PASS for execution/completeness of this audit. Integrated RTL elaboration: FAIL. Functional ECG equivalence and hardware validation: NOT RUN. Human specification review: NOT RUN. Phase 0 does not claim the reviewed-spec acceptance gate is approved, and does not start Phase 1.

## Exact invocation ledger and complete diagnostic lines

All commands below ran with working directory `C:\Users\giado\AppData\Local\Temp\ecg-phase0-i6t27i2m`. PASS/FAIL is the recorded process result; exit codes are retained. Full transcripts remain in the temporary `<check>.log` files and `tool_results.json`. No warning was promoted, hidden or suppressed.

```powershell
# vlog_version: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-version'
# vopt_version: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-version'
# vlib: PASS, exit 0
& 'C:\MentorGraphics\win64\vlib.exe' 'work'
# lint_apb_slave_if: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\apb\apb_slave_if.v'
# lint_adc_interface: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\adc\adc_interface.v'
# lint_window_buffer: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\window\window_buffer.v'
# lint_feature_extraction: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\feature\feature_extraction.v'
# lint_ai_classifier: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\ai\ai_classifier.v'
# lint_mlp_weights_rom: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\ai\mlp_weights_rom.v'
# lint_control_fsm: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\control\control_fsm.v'
# lint_uart_tx: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\uart\uart_tx.v'
# lint_top_ppg_classifier: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\top\top_ppg_classifier.v'
# elab_apb_slave_if: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.apb_slave_if' '-o' 'apb_slave_if_elab'
# elab_adc_interface: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.adc_interface' '-o' 'adc_interface_elab'
# elab_window_buffer: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.window_buffer' '-o' 'window_buffer_elab'
# elab_feature_extraction: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.feature_extraction' '-o' 'feature_extraction_elab'
# elab_ai_classifier: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.ai_classifier' '-o' 'ai_classifier_elab'
# elab_mlp_weights_rom: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.mlp_weights_rom' '-o' 'mlp_weights_rom_elab'
# elab_control_fsm: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.control_fsm' '-o' 'control_fsm_elab'
# elab_uart_tx: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.uart_tx' '-o' 'uart_tx_elab'
# elab_top_ppg_classifier: FAIL, exit 2
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.top_ppg_classifier' '-o' 'top_ppg_classifier_elab'
# lint_tb_adc_interface: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_adc_interface.sv'
# elab_tb_adc_interface: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_adc_interface' '-o' 'tb_adc_interface_elab'
# lint_tb_ai_classifier: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_ai_classifier.sv'
# elab_tb_ai_classifier: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_ai_classifier' '-o' 'tb_ai_classifier_elab'
# lint_tb_apb_slave_if: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_apb_slave_if.sv'
# elab_tb_apb_slave_if: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_apb_slave_if' '-o' 'tb_apb_slave_if_elab'
# lint_tb_control_fsm: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv'
# elab_tb_control_fsm: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_control_fsm' '-o' 'tb_control_fsm_elab'
# lint_tb_feature_extraction: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_feature_extraction.sv'
# elab_tb_feature_extraction: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_feature_extraction' '-o' 'tb_feature_extraction_elab'
# lint_tb_feature_simple: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_feature_simple.sv'
# elab_tb_feature_simple: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_feature_simple' '-o' 'tb_feature_simple_elab'
# lint_tb_top_ppg_classifier: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_top_ppg_classifier.sv'
# elab_tb_top_ppg_classifier: FAIL, exit 2
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_top_ppg_classifier' '-o' 'tb_top_ppg_classifier_elab'
# lint_tb_uart_tx: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_uart_tx.sv'
# elab_tb_uart_tx: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_uart_tx' '-o' 'tb_uart_tx_elab'
# lint_tb_window_buffer: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_window_buffer.sv'
# elab_tb_window_buffer: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_window_buffer' '-o' 'tb_window_buffer_elab'
# lint_tb_window_simple: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_window_simple.sv'
# elab_tb_window_simple: PASS, exit 0
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_window_simple' '-o' 'tb_window_simple_elab'
# lint_sim_tb_top: PASS, exit 0
& 'C:\MentorGraphics\win64\vlog.exe' '-sv' '-lint' '-work' 'work' 'C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\sim\tb_top.sv'
# elab_sim_tb_top: FAIL, exit 12
& 'C:\MentorGraphics\win64\vopt.exe' '-work' 'work' 'work.tb_top_ppg_classifier' '-o' 'sim_tb_top_elab'
```

Every compiler warning/error line, including warnings on successful commands:

```text
[elab_top_ppg_classifier: FAIL]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\top\top_ppg_classifier.v(164): (vopt-2241) Connection width does not match width of port 'paddr'. The port definition is at: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\apb\apb_slave_if.v(12).
** Error (suppressible): C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\top\top_ppg_classifier.v(164): (vopt-2912) Port 'p_irq' not found in module 'apb_slave_if' (11th connection).
[lint_tb_adc_interface: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_adc_interface.sv(226): (vlog-2623) Undefined variable: tb_adc_interface.
[elab_tb_adc_interface: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_adc_interface.sv(226): (vopt-2623) Undefined variable: tb_adc_interface.
[lint_tb_ai_classifier: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_ai_classifier.sv(291): (vlog-2623) Undefined variable: tb_ai_classifier.
[elab_tb_ai_classifier: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_ai_classifier.sv(291): (vopt-2623) Undefined variable: tb_ai_classifier.
[lint_tb_apb_slave_if: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_apb_slave_if.sv(255): (vlog-2623) Undefined variable: tb_apb_slave_if.
[elab_tb_apb_slave_if: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_apb_slave_if.sv(49): (vopt-2241) Connection width does not match width of port 'paddr'. The port definition is at: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\apb\apb_slave_if.v(12).
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_apb_slave_if.sv(255): (vopt-2623) Undefined variable: tb_apb_slave_if.
[lint_tb_control_fsm: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(33): (vlog-2623) Undefined variable: tb_control_fsm.
[elab_tb_control_fsm: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(33): (vopt-2623) Undefined variable: tb_control_fsm.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2685) [TFMPC] - Too few port connections for 'dut'.  Expected 16, found 9.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2718) [TFMPC] - Missing connection for port 'next_state_debug'.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2718) [TFMPC] - Missing connection for port 'read_addr'.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2718) [TFMPC] - Missing connection for port 'uart_send'.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2718) [TFMPC] - Missing connection for port 'mlp_valid'.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2718) [TFMPC] - Missing connection for port 'mlp_start'.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2718) [TFMPC] - Missing connection for port 'feature_read_en'.
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_control_fsm.sv(16): (vopt-2718) [TFMPC] - Missing connection for port 'feature_start'.
[lint_tb_feature_extraction: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_feature_extraction.sv(168): (vlog-2623) Undefined variable: tb_feature_extraction.
[elab_tb_feature_extraction: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_feature_extraction.sv(168): (vopt-2623) Undefined variable: tb_feature_extraction.
[lint_tb_feature_simple: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_feature_simple.sv(43): (vlog-2623) Undefined variable: tb_feature_simple.
[elab_tb_feature_simple: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_feature_simple.sv(43): (vopt-2623) Undefined variable: tb_feature_simple.
[lint_tb_top_ppg_classifier: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_top_ppg_classifier.sv(328): (vlog-2623) Undefined variable: tb_top_ppg_classifier.
[elab_tb_top_ppg_classifier: FAIL]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\top\top_ppg_classifier.v(164): (vopt-2241) Connection width does not match width of port 'paddr'. The port definition is at: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\apb\apb_slave_if.v(12).
** Error (suppressible): C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\top\top_ppg_classifier.v(164): (vopt-2912) Port 'p_irq' not found in module 'apb_slave_if' (11th connection).
[lint_tb_uart_tx: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_uart_tx.sv(32): (vlog-2623) Undefined variable: tb_uart_tx.
[elab_tb_uart_tx: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_uart_tx.sv(32): (vopt-2623) Undefined variable: tb_uart_tx.
[lint_tb_window_buffer: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_window_buffer.sv(225): (vlog-2623) Undefined variable: tb_window_buffer.
[elab_tb_window_buffer: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_window_buffer.sv(225): (vopt-2623) Undefined variable: tb_window_buffer.
[lint_tb_window_simple: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_window_simple.sv(47): (vlog-2623) Undefined variable: tb_window_simple.
[elab_tb_window_simple: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\tb\tb_window_simple.sv(47): (vopt-2623) Undefined variable: tb_window_simple.
[lint_sim_tb_top: PASS]
** Warning: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\sim\tb_top.sv(223): (vlog-2623) Undefined variable: tb_top_ppg_classifier.
[elab_sim_tb_top: FAIL]
** Error: C:\Users\giado\ECG_Project\windowBuffer_featureExtraction\sim\tb_top.sv(142): The signed/unsigned conversion is not allowed for a real expression.
```

## Final preservation checks

| Diagnostic | Result | Evidence |
|---|---|---|
| Pre-existing file bytes | PASS | All 67 files match the initial SHA-256 snapshot |
| Training repository | PASS | All 15 files unchanged; main/HEAD/index unchanged and working tree clean |
| RTL source, tests and existing documents | PASS | All 52 pre-existing files unchanged; no staged changes |
| Both original main refs | PASS | Exact kickoff SHAs retained |
| New repository files | PASS | Only docs/ecg_spec.md, docs/baseline_audit.md, docs/interface_contract.md in RTL repository |
| Commit/push/merge/deletion | PASS | None performed |
