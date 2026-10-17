# Phase 3A — ECG signed16 sample interface

Ngày thực hiện: 2026-10-16. Repository RTL trên `ECG`, HEAD `983f803b3e3d815a411c46da7ae66006a9d5af03` cộng working tree chưa commit. Training chỉ đọc: `AI_FSM_ECG@7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d`.

**PASS** cho giao tiếp ECG mới: Questa lint/elaboration, hai simulation suites, exhaustive signed16, backpressure/reset/overflow và regression MLP. **FAIL** được tái hiện ở ADC legacy: ba mẫu liên tiếp chỉ chuyển một mẫu. Verilator và FPGA synthesis/timing: **NOT RUN**. Chưa nối giao tiếp mới vào Window/Feature hoặc legacy top.

Đã đọc `AGENTS.md`, integration plan, ba báo cáo Phase 0 và các báo cáo Phase 1A/2A/2B. Thực hiện đúng slice giao tiếp số, không thay window, preprocessing, sample rate hay model.

## Review legacy và phạm vi thay thế

`adc/adc_interface.v` nhận unsigned mặc định 8-bit, chỉ bắt cạnh lên `adc_data_valid`; `mode_ppg_ecg` và `adc_clk` không dùng. Divider 16-bit trì hoãn mẫu dù nguồn đã cung cấp valid. `data_pending` và `overflow_flag` đều được ghi từ hai `always` clocked, gây cạnh tranh giữa nhận/phát và quản lý lỗi.

`top/top_ppg_classifier.v` nối `.DATA_WIDTH(8)`, `.mode_ppg_ecg(1'b0)`, `adc_clk=0`, bỏ ngỏ ADC overflow/count. `16'd400000` bị truncate; Window và Feature vẫn 8-bit/512 samples, không có ready phía sample. Top còn lỗi `p_irq`/`clk_locked` đã ghi ở Phase 0. Không ép sample signed16 qua đường 8-bit này.

Replacement authoritative của Phase 3A là [ecg_sample_interface.sv](../rtl/ecg/ecg_sample_interface.sv). Wrapper [ecg_sample_pulse_adapter.sv](../rtl/ecg/ecg_sample_pulse_adapter.sv) phục vụ nguồn strobe không có backpressure. Hai đường dùng **cùng một implementation lưu mẫu**, không nhân đôi thuật toán. Không có mode PPG, divider, ADC clock phụ, threshold hoặc offset PPG trong compile path mới.

Legacy ADC/top/testbench được giữ nguyên để tham chiếu. Do đó nguyên nhân MULTIDRIVENPROC đã được loại khỏi **replacement**, không phải đã sửa mọi legacy module trong workspace. Core mới chỉ có **một `always_ff`**, là writer duy nhất của `sample_reg`, `data_pending`, `overflow_pulse`, `overflow_flag`; wrapper không có register. Questa mới không báo multi-writer; xác nhận bằng Verilator riêng là **NOT RUN** vì thiếu executable. Chưa chạy lại integrated legacy top trong phase này; lỗi Phase 0 không được đổi thành PASS.

## Hợp đồng giao tiếp

Một clock `clk`, reset `rst_n` active-low asynchronous. Mọi input phải đồng bộ với clock và đáp ứng setup/hold; reset release phải được xử lý đồng bộ ở caller. Core không có CDC hoặc synchronizer reset-release.

| Port của `ecg_sample_interface` | Ý nghĩa |
|---|---|
| `sample_in` | Signed two's-complement 16-bit, miền integer container −32768…32767 |
| `sample_valid` / `sample_ready` | Nhận một mẫu tại rising edge khi cả hai bằng 1 |
| `sample_out` / `sample_out_valid` | Payload đã register; valid giữ đến khi consumer nhận |
| `sample_out_ready` | Consumer nhận tại rising edge khi ready && out_valid |
| `source_overflow` | Thông báo một sự kiện mất mẫu ở adapter upstream; tie 0 cho Replay không mất dữ liệu |
| `overflow_pulse` | Bản register của sự kiện loss ở edge vừa qua; một clock mỗi sự kiện, có thể cao liên tiếp nếu loss liên tiếp |
| `overflow_flag` | Sticky từ sự kiện loss đầu tiên đến reset; không tự xóa khi đọc hoặc nhận/phát mẫu |

Replay dùng **valid/ready chuẩn**: khi valid=1 và ready=0, giữ valid và payload đến edge nhận. Backpressure hợp lệ không phải overflow. Không cần hạ valid giữa hai mẫu liên tiếp; khi luôn ready, mỗi clock valid=1 là một transaction. Core không tự phát hiện producer vi phạm hợp đồng giữ payload; nguồn không thể chờ phải dùng wrapper strobe.

`sample_ready = rst_n && (!data_pending || sample_out_ready)`. Bộ đệm sâu một mẫu, không fall-through tổ hợp. Mẫu nhận ở edge t chỉ có thể được consumer nhận sớm nhất tại edge t+1: **minimum latency 1 cycle**, throughput bền vững **1 sample/clock** khi ready liên tục. Stall có thể kéo dài tùy consumer; không có latency tối đa được bảo đảm. Có đường combinational từ downstream ready tới upstream ready.

| Trạng thái trước edge | Arrival / consumer | Kết quả |
|---|---|---|
| Empty | Không valid | Giữ empty, ready=1 khi ngoài reset |
| Empty | Valid=1 | Chụp đủ 16 bit, out_valid lên sau edge; không phát cùng edge đầu |
| Full | Consumer ready=0 | Giữ nguyên mẫu và out_valid |
| Full | Consumer ready=1, không valid mới | Phát mẫu cũ, chuyển empty |
| Full | Consumer ready=1, valid mới=1 | Phát mẫu cũ và chụp mẫu mới cùng edge; không bubble, không overflow |

Payload chỉ có nghĩa khi out_valid=1. Khi empty, `sample_out` giữ dữ liệu register cuối; không được diễn giải là mẫu mới. Reset xóa register về 0, pending và cả hai cờ lỗi; ready/out_valid đều 0 trong reset. Mẫu đang chờ bị abort; không tự phát lại sau reset. Input/overflow trong reset không được nhận.

Wrapper strobe nhận `arrival_sample`, `arrival_valid`, xuất `arrival_ready` và cùng các output/flags. **Mỗi rising edge có arrival_valid=1 là một mẫu mới**, kể cả valid cao nhiều clock. Nếu full và consumer không ready, bỏ **mẫu mới**, giữ mẫu cũ; overflow_pulse và sticky flag lên sau edge. Nếu đồng thời phát mẫu cũ, arrival_ready=1 và mẫu mới được nhận, không báo overflow. Replay không nên giữ valid khi bị chặn ở wrapper này: semantics đó thuộc core ready/valid.

Wrapper chỉ chuyển giao thức số, chưa phải XADC hardware adapter. Adapter XADC tương lai phải thực hiện conversion/scale/offset, đồng bộ clock hoặc FIFO CDC nếu cần, rồi mới đưa signed16 và strobe vào wrapper. Mất mẫu là khoảng đứt trong stream; sticky flag cho downstream phát hiện, không tự sửa được RR/window. Chính sách hủy cửa sổ bị ảnh hưởng sẽ được quyết định khi tích hợp window.

**Không thêm rate divider hoặc resampler.** Tần suất mẫu do nguồn/Replay kiểm soát. Signed16 là container, không khẳng định ADC có độ phân giải 16-bit, mV, Q4.12, gain/offset hoặc preprocessing tương đương training. Dataset hiện có là feature CSV; raw ECG/annotation và physical-unit mapping vẫn **NOT RUN**. Quy trình training 500@360 → 347 samples vẫn giữ nguyên, chưa được triển khai tại đây.

## Kết quả kiểm thử thực chạy

Lượt xác nhận cuối: [build/phase3a/20261016_213725_979656](../build/phase3a/20261016_213725_979656). Summary chứa exact commands, exit codes, warning/error, PASS markers và source hashes: [phase3a_results_20261016_213725_979656.json](phase3a_results_20261016_213725_979656.json).

| Diagnostic | Kết quả | Bằng chứng |
|---|---|---|
| Legacy continuous-valid requirement | **FAIL** | `$fatal`: `FAIL LEGACY_CONTIGUOUS expected=3 actual=1`; divisor=0, ba input ở ba edge liên tiếp |
| Questa compile `-sv -lint` cho hai RTL mới + TB | **PASS** | 0 errors, 0 warnings |
| Questa elaboration core và wrapper | **PASS** | Cả hai top độc lập, 0 errors, 0 warnings |
| Replay ready/valid | **PASS** | 69.303 accepted, 69.302 delivered, 1 reset-abort, 0 dropped; 0 mismatch |
| Pulse/overflow adapter | **PASS** | 68.860 accepted, 68.859 delivered, 1 reset-abort; 1.700 arrival bị từ chối và báo loss đúng; 0 mismatch |
| Toàn miền signed16 | **PASS** | Mỗi suite gửi/nhận đủ 65.536 encoding, continuous valid, 1 sample/clock |
| Stall / nhận và phát đồng thời | **PASS** | Replay 3.761 stall cycles / 68.054 simultaneous; pulse 3.326 / 67.180 |
| Overflow semantics | **PASS** | Replay stall không báo loss; 2 upstream loss events được chốt; pulse drop-new và sticky/reset/recovery đúng |
| Reset | **PASS** | Assert giữa clock, reset full + stalled offer, clear loss flags, bỏ pending và phục hồi không phát stale data |
| Behavioral coverage | **PASS** | 8/8 tổ hợp occupancy/input-valid/output-ready; seed `0x3a16cafe`, 10.000 random cycles/suite |
| VCD | **PASS** | Replay 7.430.131 byte; pulse 7.611.010 byte; legacy 4.614 byte |
| MLP Phase 2A regression | **PASS** | Tám suites, 14/14 golden, đủ bốn class, 0 mismatch; 461 cycles không đổi |
| Guard bảo toàn summary cũ | **PASS** | `--summary docs/phase2a_results.json` bị từ chối trước khi chạy, exit 2 |
| Verilator lint | **NOT RUN** | Không thấy trên PATH hoặc thư mục tool đã kiểm tra; không cài phần mềm |
| Icarus | **NOT RUN** | Không có executable khả dụng; Questa được dùng cho phase này |
| Synthesis/timing/board/CDC validation | **NOT RUN** | Simulation 20 ns không chứng minh FPGA đạt 50 MHz |

QuestaSim-64 2024.1 / compiler 2024.02 tại `C:/MentorGraphics/win64`, được chọn bằng đường dẫn tường minh vì PATH trỏ tới ModelSim Altera cũ. Không suppress warning. Mỗi simulation mới có warning `vopt-10587` do `+acc`; compile/elaboration standalone mới không có warning.

Scoreboard dùng queue transaction độc lập: so sánh payload `!==`, kiểm tra valid/ready trước và sau edge, giữ payload khi stall, FIFO order và `accepted = delivered + reset_aborted` khi drain xong. Hai luồng quét đủ signed min/max/zero/tất cả bit patterns; random traffic dùng seed cố định. Coverage là behavioral counter/bitmap của testbench, không phải UCDB code coverage hoặc formal proof. TB không đọc/force register DUT để làm test pass.

Waveform mới: [replay_ready_valid.vcd](../build/phase3a/20261016_213725_979656/replay_ready_valid.vcd), [pulse_overflow.vcd](../build/phase3a/20261016_213725_979656/pulse_overflow.vcd). Không ghi waveform bitmap 65.536 bit của testbench để tránh file quá lớn; tín hiệu DUT/interface vẫn được ghi. Legacy reproduction có assertion thất bại thật; runner đánh dấu `FAIL` và `expected_baseline_failure=true`, tách khỏi gate replacement. Không coi legacy FAIL là legacy PASS.

Các lượt ban đầu được giữ nguyên:

- `20261016_213445_443739`: **FAIL** do coverage index dùng sample signed làm chỉ số âm. Đổi riêng index bitmap thành `$unsigned(output_sample)`; giữ nguyên signed payload/scoreboard và mọi assertion.
- `20261016_213535_757364`: **FAIL** do macro `onbreak {quit -code 1}` cũng bắt `$finish` thành công; hai suite đã có PASS marker nhưng process exit 1. Bỏ handler này, giữ `onerror`, kiểm tra exit code, Fatal/Error/FAIL và required PASS marker. `$fatal` vẫn làm diagnostic FAIL kể cả simulator trả exit 0 sau macro quit.
- `20261016_213725_979656`: **PASS** gate replacement + MLP. Không sửa RTL giữa các lượt; chỉ sửa coverage accounting và launcher. Các JSON FAIL đầu tiên vẫn tồn tại, vì vậy `docs/phase3a_results.json` là **lượt đầu**, không phải summary cuối.

## Regression MLP và tính bất biến

Sau khi sample suites PASS, runner gọi đúng regression cũ với output riêng:

```text
python -B tools/run_ecg_rtl.py --questa-dir C:/MentorGraphics/win64 --summary <new-build>/mlp_results.json
```

[MLP summary](../build/phase3a/20261016_213725_979656/mlp_results.json) và [log/VCD MLP](../build/phase2a/20261016_213808) lưu kết quả mới. Arithmetic 180 cases, ROM 164 địa chỉ/cổng, golden/protocol, signed corners và bốn overflow suites đều **PASS**. Tổng vẫn 65 accepted = 39 success + 14 expected-overflow completion + 12 reset-abort. Normalized, pre-activation, hidden, logits, class và trace vẫn bit-exact. Tám MLP VCD không rỗng.

`tools/run_ecg_rtl.py` chỉ được thêm tùy chọn `--summary` để ghi file mới trong RTL repository và từ chối overwrite khi dùng tùy chọn này. Compile list, assertions, vector generation và logic đánh giá MLP không đổi. Không ghi đè `docs/phase2a_results.json`, báo cáo Phase 0–2B, log/VCD cũ. Source/model/golden SHA-256 được kiểm tra lại trong [phase3a_integrity.json](phase3a_integrity.json): 117/118 file đã có giữ nguyên; khác biệt duy nhất là runner này. Training sạch, refs HEAD/main hai repo không đổi.

## File thêm/sửa và chạy lại

| File | Thay đổi |
|---|---|
| `rtl/ecg/ecg_sample_interface.sv` | Thêm core signed16 ready/valid, một pending sample, một writer cho mỗi register |
| `rtl/ecg/ecg_sample_pulse_adapter.sv` | Thêm wrapper arrival-strobe/drop-new/overflow dùng lại core |
| `tb/ecg/tb_ecg_sample_interface.sv` | Thêm self-checking TB parameterized cho hai loại nguồn |
| `tb/ecg/tb_legacy_adc_contiguous.sv` | Thêm test tái hiện yêu cầu contiguous-valid thất bại trên legacy |
| `tools/run_ecg_sample_tests.py` | Thêm runner, log/VCD, optional available Verilator lint, Questa và MLP regression |
| `tools/run_ecg_rtl.py` | Thêm `--summary` có guard bảo toàn kết quả cũ |
| `docs/phase3a_report.md`, `phase3a_integrity.json` | Báo cáo và bằng chứng bất biến |
| `docs/phase3a_results.json`, `phase3a_results_20261016_213535_757364.json`, `phase3a_results_20261016_213725_979656.json` | Giữ đủ ba lượt, gồm hai FAIL harness và PASS cuối |
| `build/phase3a/...`, `build/phase2a/20261016_213808` | Artifacts sinh mới trong build đã ignore; không thay artifacts cũ |

Từ repository RTL trên ECG:

```powershell
python -B tools/run_ecg_sample_tests.py
# Có thể chọn Questa đã cài bằng --questa-dir PATH.
```

Runner luôn lưu thư mục mới, không cài phần mềm. Legacy FAIL được kiểm chứng riêng; regression MLP chỉ chạy sau khi replacement suites PASS. Nếu không có tool, diagnostic tương ứng ghi NOT RUN. Không có commit/push/merge, xóa file, sửa training/main/MLP/model/golden hoặc triển khai Window/Feature. Bước tiếp theo là chốt raw sample scale/event metadata rồi thiết kế window signed16 và consumer-ready; không nối replacement vào legacy 8-bit trước khi boundary đó được kiểm chứng.
