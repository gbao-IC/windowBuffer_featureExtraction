# ECG interface contract — Phase 0 draft

Source baseline: `ECG@983f803b3e3d815a411c46da7ae66006a9d5af03`; training reference: `7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d`. No interface implementation changes were made. [ecg_spec.md](ecg_spec.md) defines feature semantics and open decisions; [baseline_audit.md](baseline_audit.md) records actual diagnostics.

## Current module boundaries

All active RTL uses rising-edge clocks and active-low reset inputs. This describes declarations/logic, not proof of reset correctness.

| Producer → consumer | Current payload/control | Actual behavior and diagnostic result |
|---|---|---|
| External → top | `sys_clk`, `sys_rst_n` | FAIL: `rst_n = sys_rst_n & clk_locked`; `clk_locked` has no driver. No PLL or PS clock wrapper |
| APB host → `apb_slave_if` | Top address/data 32 bits; slave address 8 bits; `psel,penable,pwrite` | FAIL: top truncates address; does not export `pready/pslverr`; requests nonexistent `p_irq` port |
| External ADC → `adc_interface` | Unsigned `adc_data[7:0]`, `adc_valid`; 16-bit divisor | Rising edge of valid fills one pending latch; rate tick consumes it. FAIL: two always blocks write pending/overflow flags; no coherent CDC handshake; `adc_clk` and mode input unused |
| ADC → window | `sample_out[7:0]`, one-cycle `sample_valid`; no ready | Window accepts only when enabled. FAIL: no upstream backpressure; ADC overflow not connected to system status |
| Window → feature | 9-bit read address, `read_en`, 8-bit `frame_out`; `window_ready` pulse and bank ID | Registered read address, combinational RAM data using live bank. FAIL: bank not reserved for reader; final sample not written; no overlap implementation |
| Master → window/feature | `window_en`, `feature_start`, `feature_read_en` | FAIL: read-enable is never asserted; feature start occurs before a full window; feature module ignores its `read_enable` input |
| Feature → MLP | Twelve signed 16-bit fields in the specified order; `feature_valid` | FAIL: mixed integer/Q12 outputs, incompatible with scaler. No feature snapshot in active MLP |
| Master → MLP | `mlp_start`; enable from APB; `mlp_valid` left unconnected | FAIL: start stays high through several states; master reproduces layer cycle counts instead of consuming completion |
| MLP → master/result | 2-bit class; `done`, `overflow`; 8/4 debug arrays, 32 bits each | FAIL: top leaves MLP done disconnected. `class_code` has no reset assignment; overflow is only cleared, never detected |
| ROM → MLP | Separate `mlp_weights_rom`: 8-bit address, registered 16-bit data, 164 words | FAIL: ROM not instantiated by top/classifier; invalid hardcoded relative file path; classifier's internal loader regs undriven |
| Master → UART | `uart_send`, `tx_data={6'b0,class_code}`, 16-bit baud divisor | UART takes start while idle/enabled and returns busy/done. FAIL: master does not wait for either; no result queue |
| APB → IRQ | Internal `p_irq <= sys_done && ctrl_reg[2]` | FAIL: internal reg is not a module port; event is not sticky or acknowledged |

`hr_top` in the training reference is a separate alternative: `start` moves IDLE→LOAD, `ready` means LOAD, and `valid` captures all twelve signed-16 feature ports. It then normalizes, runs FC1/ReLU/FC2/argmax and asserts `done`; DONE waits for `!start` before returning. Two 8-bit addresses drive `Gowin_DPB`, with read latency assumed by its counters. ROM serialization was checked; latency and transaction correctness are NOT RUN. Its comments calling ZC and RR integer counts contradict the Python feature units.

## Current APB register map

Source: `apb/apb_slave_if.v`. This map is recorded for migration, not endorsed as an AMBA-compliant implementation.

| Offset | Register | Current fields/reset |
|---|---|---|
| `0x00` | CTRL | bit 0 enable; bit 1 start request; bit 2 IRQ enable; bit 4 soft reset; reset 0 |
| `0x04` | STATUS | bit 0 busy, bit 1 done, bit 3 overflow; no implemented error at bit 2 |
| `0x08` | THRESH | low 16 bits; reset 80; only low 8 bits used by feature detector |
| `0x0C` | BAUD | low 16 bits; reset `0x0358=856`, which differs from UART parameter 868 |
| `0x10` | RESULT | bits 1:0 live class code; no transaction ID or validity latch |
| `0x14` | VERSION | `0x0100` |
| `0x18` | CONFIG | bit 0 BLE enable, bit 1 UART enable; register resets to 0 but output UART enable resets to 1 |

Writes occur during SETUP (`psel && pwrite && !penable`), before an accepted ACCESS transfer. Reads are registered whenever selected and reading; `pready` is a registered `psel && penable`; `pslverr` is always zero. Start self-clears on the following clock, but CTRL readback retains the written start bit. Soft reset reaches only the window. Address decoding ignores high bits. Diagnostic result: FAIL for coherent bus/transaction behavior; exact waveform-level protocol testing is NOT RUN in this phase.

## Proposed logical interfaces for implementation review

The following are proposed obligations, not existing ports or an approved numeric format. Verification result for each proposed boundary is NOT RUN.

| Boundary | Payload / encoding | Acceptance and lifetime |
|---|---|---|
| Replay → sample adapter | Signed 16-bit sample container; physical unit, scale and sample-index width UNDECIDED | Accept on `sample_valid && sample_ready`; hold payload under backpressure. Container does not imply 16-bit ADC or Q4.12 |
| Marker/RR → window | Event ID, source sample index, current/previous RR in seconds or an explicitly specified tick-to-second conversion | Associate RR with the same accepted event/window. Annotation assistance must be exposed in the demo description |
| Window → feature | Exactly 347 samples for the resampled-reference path, addresses 0..346, plus RR/event metadata | Freeze a complete window until consumed; explicitly pipeline RAM response-valid with address; never read unwritten last sample |
| Feature → scaler/MLP | Atomic 12-element vector in `ecg_spec.md` order; widths/scales UNDECIDED | Accept once when ready; capture vector and event metadata together. Do not require live source fields to remain valid throughout inference |
| Model ROM → MLP | Historical 164-word address order; new word/field widths UNDECIDED due to clipping | Explicit synchronous read latency, address/data alignment, valid address range and signed interpretation; model must be loaded before ready |
| MLP → result sink | Class ID 0..3, event ID, valid/error metadata; debug values not required in production | Exactly one result per accepted non-aborted transaction; stable until accepted; choose lowest class index on equal logits |
| Result → CSR/UART | Same latched result transaction | Reading status must not erase an event accidentally; result cannot be overwritten before the chosen consumption policy allows it |

Recommended master sequence: IDLE/ACQUIRE → WAIT_WINDOW → START_FEATURE → WAIT_FEATURE → START_MLP → WAIT_MLP → LATCH_RESULT → optional WAIT_UART. The internal MLP FSM owns normalization and layers. A result must depend on real completion, not copied cycle-count estimates.

Recommended initial policy is one in-flight inference, explicit backpressure and no silent loss. Final handling of start while busy, source that cannot pause, queue depth, invalid RR and transaction IDs remains UNDECIDED (U7). Define reset abort semantics explicitly: a reset-aborted transaction must not emit an old class as a new result. Reset release must be synchronized to the working clock; asynchronous input requires a proper CDC adapter, not independent synchronization of a data bus.

## Numeric boundary requirements

- Preserve the 12 feature meanings and units before quantization. ZC is a ratio; RR/difference is seconds; variance uses amplitude squared.
- Specify every field as signedness, width, fraction bits, range, rounding and saturation. These are currently UNDECIDED for the new design.
- Widen subtraction/products/accumulators before narrowing; align each bias with its accumulator's binary point; make ReLU and argmax signed comparisons.
- Do not equate historical HEX equality with approved numerical accuracy. Historical `weight.hex` is a known-clipped compatibility artifact.
- Keep expected raw features, scaler outputs, hidden values, logits and class IDs in a traceable test package. Fixed-point implementation should be bit-exact to its independent integer model; floating tolerance and allowable class disagreement remain UNDECIDED (U5/U8).

## UART and board integration

Current wire format is one binary byte `0x00..0x03`, UART 8N1, LSB first; there is no ASCII digit, heart rate, checksum, packet header or RX implementation. Proposed first demo may preserve this one-byte format, but framing/transaction metadata and final baud are UNDECIDED. Accept a UART transaction only when idle/enabled, and account for TX completion separately from inference completion.

The plan's FPGA target is `xc7z020clg484-1`, 50 MHz working clock. Installed Vivado part support, generated clock/reset implementation, board pin constraints and PS-versus-PL UART routing are NOT RUN. Existing 100 MHz constants and Gowin synthesis commands cannot establish a ZC702 build. Proposed PS control path: PS AXI interconnect → AXI-to-APB bridge → repaired CSR interface. Only synthesizable RTL/model initialization enters synthesis; directed SV/UVM belongs to simulation.

## Required future boundary tests

All are NOT RUN against a corrected ECG design in Phase 0:

1. First/last sample and all 347 positions; RAM latency; event association; reader/writer collision; exact accepted sample count.
2. Negative/full-scale/zero inputs, zero-crossing transitions through zero, 173/174 half-window split, RR startup/history and epsilon handling.
3. ROM addresses 0/11/12/23/24/119/120/127/128/159/160/163, invalid addresses, load completion and registered-read timing.
4. Back-to-back transactions, start while busy, result backpressure, reset during each stage, no duplicate or missing completion.
5. All 12 raw features, all 12 normalized values, 8 hidden values, 4 logits and argmax against independent references; ties and numeric overflow.
6. APB setup/access/wait/error behavior, sticky completion/IRQ policy, result lifetime and all reset/readback values.
7. UART bit-level decoding, baud divisor boundaries, busy rejection, disabled operation, class-byte ordering and TX completion.
