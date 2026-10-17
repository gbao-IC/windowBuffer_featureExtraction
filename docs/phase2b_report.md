# Phase 2B — Chuẩn bị synthesis/timing cho standalone ECG MLP

Ngày: 2026-10-16. Target: ZC702, `xc7z020clg484-1`, clock mục tiêu 50 MHz (20 ns).

**PASS**: regression Phase 2A chạy lại, kiểm tra package và script chuẩn bị. **NOT RUN**: Vivado synthesis, implementation, mapping BRAM, utilization và timing phần cứng. Chưa tìm thấy Vivado khả dụng; không cài phần mềm và không tối ưu/sửa RTL.

Khi nhận yêu cầu tiếp tục, Phase 2B đã bắt đầu: regression đã xong và ba file Tcl/XDC/runner đang được hoàn thiện. Phần tiếp tục chỉ kiểm tra script và bổ sung bằng chứng/báo cáo; không chạy lại Phase 1A hoặc lặp regression Phase 2A.

## Trạng thái workspace và bảo toàn dữ liệu

| Repository | Branch / HEAD | Main ref | Working tree |
|---|---|---|---|
| `AI_FSM_ECG` | `main` / `7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d` | Cùng SHA | **PASS**: sạch, chỉ đọc |
| `windowBuffer_featureExtraction` | `ECG` / `983f803b3e3d815a411c46da7ae66006a9d5af03` | `9e33a48dab0d5d517ac8adaf4000dca9f8342cda` | Các file Phase 0/1A/2A và Phase 2B chưa commit; không đổi tracked source |

Remotes giữ nguyên: training `https://github.com/gbao-IC/AI_FSM_ECG.git`; RTL `https://github.com/gbao-IC/windowBuffer_featureExtraction.git`. Không fetch, checkout, commit, push, merge hoặc xóa file.

Đã đọc `AGENTS.md`, `docs/ECG_INTEGRATION_PLAN.md`, báo cáo Phase 1A và Phase 2A. Đối chiếu snapshot đầu Phase 2B: **108/109 file giữ nguyên SHA-256**; file duy nhất được runner hiện có cập nhật là `docs/phase2a_results.json`, chỉ mục của lần regression mới. Việc cập nhật này xảy ra ở lượt chạy đã được yêu cầu trước thông điệp tiếp tục; không ghi đè log/VCD cũ. Báo cáo Phase 2A vẫn giữ nguyên, trỏ tới lượt lịch sử `20261016_164656`; JSON mới trỏ tới `20261016_170307`. Một bản kết quả mới được lưu riêng tại [phase2b_regression.json](phase2b_regression.json).

Training, toàn bộ RTL cũ/mới, testbench, golden reference, vector và báo cáo Phase 0/1A/2A đều không đổi. Hai ref main không đổi. Chi tiết: [phase2b_integrity.json](phase2b_integrity.json). Không sửa ADC, Window Buffer, Feature Extraction, APB hoặc UART.

## Bằng chứng thực chạy

Lệnh regression đã chạy một lần: `python -B tools/run_ecg_rtl.py`. QuestaSim-64 2024.1 từ `C:/MentorGraphics/win64`; compiler/simulator 2024.02. Log và tám VCD mới: [build/phase2a/20261016_170307](../build/phase2a/20261016_170307).

| Diagnostic | Trạng thái | Kết quả |
|---|---|---|
| Questa `vlog -sv -lint` và `vopt` | **PASS** | 0 errors, 0 warnings ở compile/elaboration |
| Arithmetic | **PASS** | 180 signed rounding/range cases |
| ROM RTL | **PASS** | 164 địa chỉ mỗi cổng, latency 1 clock, enable/invalid/reset |
| Golden + handshake/reset | **PASS** | 14/14 golden cases bit-exact; class mask `0xF`; mismatch 0 |
| Signed corners | **PASS** | INT32 min/max, tie RNE, ReLU, signed logits/argmax |
| Bốn overflow suites | **PASS** | Normalize, FC1, FC2 dương/âm; repeat và recovery không reset |
| Waveforms | **PASS** | Tám VCD không rỗng, giữ nguyên waveform cũ |
| Model input preflight | **PASS** | 164 word 32-bit, SHA khớp Phase 1A |
| Python/Tcl script checks | **PASS** | 11/11 tests; Python 3.12.10, Tcl 8.6.15 |
| Verilator / Icarus | **NOT RUN** | Không có executable khả dụng; regression dùng Questa |
| Vivado API / installed target part | **NOT RUN** | Không có Vivado để kiểm chứng API/part database |
| Vivado synthesis / implementation | **NOT RUN** | Không có executable được tìm thấy |
| BRAM mapping / netlist ROM equivalence | **NOT RUN** | RTL simulation không chứng minh primitive INIT sau synthesis |
| FPGA timing/resource signoff | **NOT RUN** | Không có netlist đặt/định tuyến hoặc báo cáo timing |

Tám suite simulation đều PASS, tổng 65 accepted = 39 success + 14 expected-overflow completion + 12 reset-abort. Success vẫn **461 cycles**, không đổi handshake/latency. Các warning simulation `vopt-10587` do `+acc` vẫn được giữ trong log, một warning mỗi suite; không phải lỗi số học.

Test script chạy bằng `python -B -m unittest discover -s tests -p test_ecg_synthesis_flow.py -v`, exit 0. Kiểm tra hash model, từ chối word thiếu/sai width/sai hash, thiếu tool không tự thay tool, parser không biến missing timing thành zero, giữ số slack âm/endpoint count, Tcl/XDC đầy đủ cấu trúc, constraint arguments và từ chối mode/output directory không hợp lệ. Các test Tcl dùng interpreter và stub rõ ràng cho lệnh Vivado: **không kiểm chứng synthesis API hoặc port matching trên netlist**. [phase2b_script_tests.json](phase2b_script_tests.json) và [log](../build/phase2b/script_tests_1.log) lưu kết quả.

Runner synthesis đã chạy: `python -B tools/run_ecg_synthesis.py`. [phase2b_results.json](phase2b_results.json) lưu trạng thái **NOT RUN**, hash các input, thư mục staging và lý do. Không sinh dữ liệu utilization/slack giả; các giá trị phần cứng chưa có giữ null/rỗng.

## Tool discovery

Không thấy `vivado`/`vivado.bat` trên PATH; `XILINX_VIVADO`, `XILINX`, `RDI_APPROOT` trống. Đã kiểm tra các thư mục vendor ở C/D/E, `C:/Program Files`, `C:/Program Files (x86)`, workspace, MSYS2 và danh sách uninstall Windows. `C:/Xilinx` chỉ thấy `14.7` và `xic`; không thấy Vivado launcher. ISE 14.7 không được dùng thay cho flow Vivado đã yêu cầu.

Có giới hạn truy cập ở gốc E:, WindowsApps, CocCoc CrashReports và một thư mục temp venv. Vì vậy kết luận là **không tìm thấy Vivado khả dụng trong phạm vi đã kiểm tra**, không khẳng định tuyệt đối mọi ổ đĩa đều không có cài đặt. Chưa cài phần mềm. Runner hỗ trợ truyền đường dẫn Vivado đã cài bằng `--vivado`.

## Flow synthesis mới và giới hạn out-of-context

| File mới | Vai trò |
|---|---|
| [run_vivado.tcl](../synthesis/ecg/run_vivado.tcl) | Non-project flow trong in-memory project: synth, tùy chọn opt/place/phys-opt/route, xuất DCP/netlist/reports |
| [ecg_mlp_ooc.xdc](../synthesis/ecg/ecg_mlp_ooc.xdc) | Clock và ngân sách timing tại biên core |
| [run_ecg_synthesis.py](../tools/run_ecg_synthesis.py) | Guard branch ECG, hash/format model, staging input, tìm tool, lưu log/JSON |
| [test_ecg_synthesis_flow.py](../tests/test_ecg_synthesis_flow.py) | Kiểm tra package, parser, Tcl/XDC và guard không ghi đè output |
| `docs/phase2b_*.json`, báo cáo này | Regression, script tests, hardware NOT RUN và integrity evidence |

Không thay legacy `synthesis/run_synth.tcl` (Gowin/PPG). Compile list mới chỉ có package Q12.20 → ROM → MLP core; không gồm testbench, legacy top hoặc peripheral. Model giữ nguyên [model_q12_20.hex](../tests/vectors/model_q12_20.hex), SHA-256 `44b77346ac8d1636c2ccd30e2dce936e993560bfb2d37d4aa4d4e6250a847f41`.

Mỗi run tạo thư mục `build/phase2b/<timestamp>/input` mới, sao chép sáu input gồm ba RTL, model, Tcl và XDC, ghi hash trước chạy và kiểm tra lại sau chạy. Tcl đặt working directory về staged root, giữ đường dẫn `tests/vectors/model_q12_20.hex` mặc định trong RTL. Không sửa string parameter, không lấy model fixture corner/overflow. Cách này tránh phụ thuộc working directory bên ngoài và tránh override string generic không được hỗ trợ ở một số phiên bản Vivado. [AMD UG901](https://docs.amd.com/r/2023.2-English/ug901-vivado-synthesis/Running-Synthesis-with-Tcl?contentId=ojV50v3aUJFAuacPdqh4Gg)

Tcl từ chối output directory đã tồn tại; runner tạo summary tên mới nếu `docs/phase2b_results.json` đã có. Không xóa run cũ. `general.maxThreads=1`; tool version, source hashes và command được lưu khi có tool. Cùng source/options/tool version giúp tái lập flow, không cam kết DCP/placement giống byte giữa các phiên bản Vivado.

Top là `ecg_mlp_core`, `synth_design -mode out_of_context`: giữ tất cả debug outputs để tránh loại bỏ phép tính khi đo baseline. Không chèn I/O pads hoặc ép hơn một nghìn cổng debug ra package pins. Kết quả sau này sẽ là tài nguyên của core với debug còn quan sát được, chưa phải cấu hình sản phẩm tối thiểu.

OOC module analysis không tạo bitstream. `HD.CLK_SRC` mô tả vị trí BUFG bên ngoài giả định, không tạo clock vật lý; clock và interface nets chưa có routing của hệ thống cuối. Không có partition-pin placement cho tái sử dụng physical checkpoint. Ngay cả khi route OOC xong, phải phân biệt timing core với timing board/top-level. [AMD UG905 — OOC constraints](https://docs.amd.com/r/en-US/ug905-vivado-hierarchical-design/Out-of-Context-Design-Constraints), [AMD UG896 — standalone IP timing limits](https://docs.amd.com/r/2021.2-English/ug896-vivado-ip/Examining-Standalone-IP)

## Hợp đồng timing 50 MHz

| Constraint | Giá trị / phạm vi | Cơ sở |
|---|---|---|
| `create_clock ecg_clk` | Period 20 ns, waveform 0/10 ns, port `clk` | Mục tiêu người dùng |
| Clock uncertainty | Setup 0,200 ns; hold 0,100 ns | Ngân sách kỹ thuật giả định, chưa đo jitter |
| Clock transition | 0,200 ns | Giả định OOC |
| Input delay | Min 0 ns / max 5 ns, mọi input trừ `clk` | Ngân sách same-clock fabric caller, chưa có interface tích hợp |
| Input transition | 0,500 ns | Giả định biên core |
| Output delay | Min 0 ns / max 5 ns, mọi output gồm debug | Ngân sách consumer cùng clock |
| Clock context | `HD.CLK_SRC BUFGCTRL_X0Y0`; Tcl kiểm tra site tồn tại | Vị trí giả định cho OOC; chưa gắn với clock ZC702 thực |
| Reset | `rst_n` nằm trong input-delay budget | Giả định deassertion đồng bộ, phải đạt recovery/removal |
| Timing exceptions | Không false-path, không multicycle | Mọi arithmetic/register stage vẫn chịu clock 20 ns |
| Pin / board constraints | Chưa có trong slice này | OOC; chưa sinh bitstream |

Reset vẫn assert bất đồng bộ ở RTL, không có synchronizer reset-release trong core. XDC không che đường reset bằng false path; giả định deassertion phải được caller thực hiện và xác minh khi tích hợp. Các budget 5 ns/uncertainty là lựa chọn đo standalone, không suy ra từ board hoặc ADC. `create_clock` chỉ khai báo yêu cầu STA, không tạo ra clock 50 MHz trên FPGA.

## Resource, timing và ROM

| Đại lượng phần cứng | Kết quả thực đo |
|---|---|
| LUT / FF | **NOT RUN** |
| DSP48E1 | **NOT RUN** |
| RAMB18E1 / RAMB36E1 | **NOT RUN** |
| WNS / TNS sau synthesis | **NOT RUN** |
| WNS / TNS / WHS / THS sau route | **NOT RUN** |
| Critical setup/hold paths | **NOT RUN** |
| DRC, unconstrained paths, route completeness | **NOT RUN** |
| Model INIT bit-exact trong synthesized netlist | **NOT RUN** |

Flow sẽ xuất utilization tổng/hierarchy, histogram primitive thực tế, thuộc tính BRAM gồm `INIT_*`/`INITP_*`, read/write widths, output registers, LOC; timing summary setup/hold/unconstrained, 20 setup paths, 20 hold paths và register-to-register paths; clocks, exceptions, check_timing, DRC, route status, DCP và functional netlist. WNS/TNS được lấy từ toàn bảng Design Timing Summary, không cộng từ danh sách critical paths bị giới hạn. [AMD UG835 — timing summary](https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/report_timing_summary)

`bram_presence.tsv` chỉ kiểm tra có primitive BRAM; không tự chứng minh đúng dual-port latency hoặc toàn bộ INIT. Hash input đúng, RTL ROM test PASS và INIT nonzero chưa đủ chứng minh netlist tương đương. Sau khi có Vivado cần review configuration/address wiring và replay 164 địa chỉ mỗi cổng trên functional netlist với Xilinx simulation libraries trước khi nâng gate ROM equivalence lên PASS. Command completion marker cũng không đồng nghĩa timing signoff.

Review kiến trúc **PASS** về tính nhất quán với Phase 2A: 12→8→4, normalization trước FC1; signed33 subtraction, signed65 normalize product, signed64 MAC product, signed68 accumulator; RNE sau full dot product; overflow trước narrowing/ReLU; tie argmax giữ index nhỏ nhất. ROM đọc đồng bộ một clock, q-data không reset; valid có reset. Handshake vẫn chụp input tại start&&ready, done pulse, valid giữ đến accept/reset, start cần rearm, busy pulse bị bỏ qua. Không thay hành vi đã kiểm chứng.

Phân tích chưa phải utilization: ROM payload 164×32 = 5.248 bit. Dual-read 32-bit phù hợp một RAMB36E1 hoặc nhiều RAMB18E1 tùy mapping; capacity nhỏ không đảm bảo vừa một RAMB18 true-dual-port. Multiplier signed33×32 vượt một DSP48E1 25×18; accumulator 68 bit vượt đường arithmetic native 48 bit, nên có thể cần nhiều DSP/fabric carry. Số DSP/BRAM thực và timing vẫn chưa biết. [AMD DSP48E1](https://docs.amd.com/r/2024.1-English/ug953-vivado-7series-libraries/DSP48E1), [RAMB18E1](https://docs.amd.com/r/2021.1-English/ug953-vivado-7series-libraries/RAMB18E1), [RAMB36E1](https://docs.amd.com/r/2022.2-English/ug953-vivado-7series-libraries/RAMB36E1)

Đường cần chú ý khi có timing report: chọn snapshot/trừ mean → shared multiply → product register; dynamic mux normalized/hidden → multiply; product/accumulator → adder 69-bit; accumulator → RNE/range check/ReLU. Đây là ứng viên từ source, không phải critical path đo được. Chưa có ngân sách LUT/DSP/BRAM được chốt riêng cho core; không thể kết luận đạt budget chỉ từ device capacity. 461 cycles tương đương 9,22 µs **nếu** đạt 50 MHz, chưa phải latency đo trên board.

## Bước tiếp theo và lệnh tái lập

Từ repository RTL trên ECG, khi có Vivado đã cài và device support Zynq-7000:

```powershell
python -B tools/run_ecg_synthesis.py --vivado 'C:/Xilinx/Vivado/<version>/bin/vivado.bat' --stage synth
python -B tools/run_ecg_synthesis.py --vivado 'C:/Xilinx/Vivado/<version>/bin/vivado.bat' --stage route
```

Mỗi lệnh là một run độc lập; `route` bao gồm synthesis. Có thể chạy chỉ lệnh route để tránh lặp synthesis. Runner kiểm tra part database, giữ transcript và warning/error thực. Exit contract: 0 = commands hoàn tất, 1 = lỗi flow/preflight, 2 = thiếu Vivado/NOT RUN; 0 không chứng minh timing/ROM signoff.

Chưa có bằng chứng cần tối ưu RTL. Nếu timing report chỉ ra đường trừ/mux/multiply là nút thắt, thay đổi nhỏ nên review trước là register operand sau subtraction/mux và thêm state tương ứng; giữ product 65 bit và mọi quy tắc RNE/overflow. Nếu adder 68-bit là nút thắt, xem xét chia carry qua chu kỳ với tổng đầy đủ trước round. Nếu area là vấn đề, cân nhắc partial-product multiplier nhiều chu kỳ, không giảm precision. Các thay đổi này đều có thể đổi latency, cần phê duyệt hợp đồng và chạy lại toàn bộ regression bit-exact/reset/overflow/handshake. **Chưa triển khai tối ưu nào**.

Phần chuẩn bị Phase 2B đã thực hiện; gate synthesis/timing phần cứng còn **NOT RUN** chờ Vivado. Các vấn đề dataset/checkpoint provenance và patient overlap từ Phase 1A vẫn giữ nguyên; không huấn luyện lại hoặc mở rộng tích hợp trong lượt này.
