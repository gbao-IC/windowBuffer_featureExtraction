# Phase 2A — Standalone ECG MLP RTL

Ngày chạy: 2026-10-16. Integration branch: `ECG`, HEAD `983f803b3e3d815a411c46da7ae66006a9d5af03` cộng các file Phase 2A chưa commit. Training reference chỉ đọc: `7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d`. Không nối core vào datapath hiện có.

**Kết quả Phase 2A: PASS cho lint/elaboration Questa và regression RTL độc lập.** 14/14 golden cases khớp bit-exact, đủ bốn class dự đoán; không còn mismatch. Synthesis, FPGA timing và utilization: **NOT RUN**. Các hạn chế provenance/training trong Phase 1A vẫn giữ nguyên.

## File và phạm vi thay đổi

| File/thư mục mới | Vai trò |
|---|---|
| [ecg_q12_20_pkg.sv](../rtl/ecg/ecg_q12_20_pkg.sv) | RNE và kiểm tra kết quả signed32 |
| [ecg_model_rom.sv](../rtl/ecg/ecg_model_rom.sv) | ROM 164×32, hai cổng đọc đồng bộ, initialization từ file model |
| [ecg_mlp_core.sv](../rtl/ecg/ecg_mlp_core.sv) | Core authoritative cho Stage A: normalize → FC1 → ReLU → FC2 → argmax |
| [tb/ecg](../tb/ecg) | Ba testbench: arithmetic, ROM, MLP/handshake/reset/overflow |
| [export_ecg_sv_vectors.py](../tools/export_ecg_sv_vectors.py) | Kiểm tra hash/trace Phase 1A rồi xuất scoreboard và fixture có kiểm chứng Python |
| [run_ecg_rtl.py](../tools/run_ecg_rtl.py) | Lint, elaboration, tám simulation suites, VCD, log và JSON summary |
| [tests/vectors/phase2a](../tests/vectors/phase2a) | Vector SV 68-bit, ROM fixture dùng riêng cho kiểm thử, manifest/hash |
| `.gitignore` | Chỉ ignore `/build/` để tránh đưa simulator work/VCD vào source |
| `docs/phase2a_*.json`, báo cáo này | Bằng chứng regression và kiểm tra bất biến |

Core mới là implementation dùng cho ECG Stage A. Các core cũ được giữ nguyên để bảo toàn baseline; chúng không nằm trong compile list của regression này. Không sửa training, Phase 1A reference/artifacts, ADC, Window Buffer, Feature Extraction, APB, UART hoặc legacy top/testbench.

## Kiến trúc và số học

Core chụp nguyên tử 12 input signed32. FSM lần lượt chuẩn hóa 12 feature, tính 8 neuron FC1, ReLU, 4 neuron FC2 và argmax. Dùng **một phép nhân signed33×signed32 dùng chung** và một đường accumulator tuần tự; 140 phép nhân/giao dịch gồm 12 normalize và 128 weight MAC. Bias lấy từ ROM, căn binary point trước khi cộng.

| Bước | Hợp đồng đã triển khai |
|---|---|
| Feature/parameter/activation/logit | Signed32 Q12.20, gồm sign trong 12 bit nguyên; F=20 |
| Trừ mean | Sign-extend hai toán hạng rồi trừ signed33 |
| Normalize product | Signed65, F=40 |
| MAC product | Signed64, F=40; shared multiplier tạo 65 bit, kiểm tra bit 64 là sign extension của bit 63 trước narrowing |
| Accumulate | Signed68, F=40; adder 69 bit kiểm tra overflow trước khi ghi 68 bit |
| Bias | Sign-extend signed32 thành 68 bit, `<<20` |
| Round | Chỉ sau normalize/full dot product; nearest, ties-to-even |
| Range check | Kiểm tra kết quả RNE còn vừa signed32 trước store hoặc ReLU; không saturate/wrap âm thầm |
| ReLU/argmax | So sánh signed; tie giữ class ID nhỏ nhất; không softmax |

RNE dùng phép chia floor tương đương arithmetic shift và remainder 20 bit không âm. Tăng quotient khi remainder lớn hơn nửa hoặc bằng nửa và quotient lẻ. Ví dụ `-0,5 → 0`, `-1,5 → -2`, `-2,5 → -2`. Kết quả RNE được giữ 49 bit để kiểm tra miền trước lấy 32 bit. Đây là đúng hợp đồng `fixed_infer()` Phase 1A, không đổi định dạng để giảm tài nguyên.

Debug ports xuất normalized[12], pre-activation[8], hidden[8], logits[4]. Trace event mang product normalize hoặc accumulator hoàn chỉnh, với stage/index và giá trị signed68. Khi nối vào thiết kế sản phẩm sau này, debug không sử dụng có thể bị synthesis loại bỏ; không có `keep/dont_touch` ép giữ.

## ROM và latency

Model thật vẫn là [model_q12_20.hex](../tests/vectors/model_q12_20.hex): 164 word 32 bit, không thay nội dung hoặc thứ tự. Địa chỉ: mean 0–11, inverse-scale 12–23, W1 24–119, b1 120–127, W2 128–159, b2 160–163; output-neuron-major.

`ecg_model_rom` dùng `$readmemh` constant initialization và `rom_style="block"`, hai read process clocked. Không reset memory/read-data register; chỉ reset valid. Đây là cấu trúc để inference Xilinx; việc Vivado map thành BRAM cụ thể **NOT RUN**.

- Địa chỉ/enable có trước rising edge; data/valid tương ứng xuất hiện sau edge đó: latency một clock của ROM.
- Core đưa request ở state REQ, tiêu thụ data ở edge tiếp theo trong MULT/LOAD, rồi register product trước ADD/ROUND.
- `en=0` hoặc address 164–255: valid=0, data=0. Hai cổng enable độc lập. Reset xóa valid ngay.
- ROM test đọc cả 164 địa chỉ trên cả hai cổng theo thứ tự ngược nhau, gồm first/last, biên các vùng model, đọc liên tiếp, disable, invalid address và reset: **PASS**.
- Khi đưa vào project Vivado, thêm file HEX vào project và đặt `MODEL_FILE`/`INIT_FILE` đến đường dẫn resolve được từ working directory của build. Không có đường dẫn tuyệt đối đến máy tác giả trong RTL.

## Handshake/reset đã chọn cho standalone core

Đây là hợp đồng Phase 2A, chưa thay interface top-level Phase 0.

| Signal/sự kiện | Quy tắc |
|---|---|
| `start && ready` tại rising edge | Nhận một request, chụp 12 feature; xóa valid/error/class cũ |
| `ready` | Reset đã nhả, FSM IDLE và start đã được rearm |
| `busy` | FSM đang xử lý; không nhận vector thứ hai |
| Rearm | Sau mỗi lần nhận, phải quan sát `start=0` tại một rising edge trước lần nhận tiếp theo; có thể rearm khi busy |
| Start giữ cao từ lần nhận | Không tự retrigger khi tính xong; ready giữ thấp đến khi rearm |
| Pulse start nằm hoàn toàn khi busy | Bị bỏ qua; không có pending-request queue |
| Start mới giữ cao qua lúc busy kết thúc | Nếu đã rearm, level còn cao tại `ready` là request mới và được nhận tại edge đó; producer phải giữ đúng payload đến edge nhận |
| Thành công | `done=1` một chu kỳ, `valid=1`, `overflow=0`, `error_stage=0`, class 0–3 |
| Sau thành công | valid/class giữ đến request được nhận tiếp theo hoặc reset; không có result-ready/backpressure trong slice này |
| Overflow | Hủy tính toán còn lại; done pulse, valid=0, overflow=1; `error_stage` 1=normalize, 2=FC1, 3=FC2 |
| ROM/FSM error | done pulse, valid=0, error_stage=4; overflow chỉ dành cho lỗi số học |
| Reset | Active-low asynchronous; abort request đang chạy, xóa result/error/debug/control; không phát done cho request bị abort |

Trên lỗi/accept/reset, class_id=0 chỉ là giá trị clear; không được đọc thành nhãn Normal nếu valid=0. Các debug arrays có thể chứa kết quả từng phần trong lúc busy hoặc khi lỗi; chỉ dùng trace/valid đúng giao dịch. Không có CDC hay đồng bộ reset-release trong core standalone: caller phải cung cấp clock và reset-release phù hợp khi tích hợp sau này.

## Kết quả thực chạy

Tool: `C:/MentorGraphics/win64`, QuestaSim-64 **2024.1**, compiler/simulator 2024.02. Lượt cuối: [build/phase2a/20261016_164656](../build/phase2a/20261016_164656). [phase2a_results.json](phase2a_results.json) lưu exact command, return code, từng warning, PASS marker, SHA-256 source và đường dẫn log/VCD.

| Diagnostic | Kết quả | Quan sát |
|---|---|---|
| `vlog -sv -lint` package/ROM/core/3 TB | PASS | 0 errors, 0 warnings |
| `vopt` standalone core | PASS | 0 errors, 0 warnings |
| Arithmetic | PASS | 180 ca, rational Python oracle; ±tie, hai phía tie, signed32 boundary, signed68 min/max, random seed cố định |
| ROM | PASS | Cả 164 địa chỉ mỗi cổng, latency/enable/reset/invalid address |
| Golden + protocol | PASS | 14/14 original cases bit-exact, class mask `0xF`; 29 completion thành công, 12 reset-abort, 41 accepted |
| Signed corner model | PASS | 4 vector riêng + 2 repeat; INT32_MIN/MAX, số âm, tie RNE, ReLU, logits âm và argmax hòa |
| Normalize overflow | PASS | Hai input dương/âm, repeat, rồi một success không reset; 5 completion |
| FC1 overflow | PASS | Dương/âm trước ReLU, repeat, rồi success không reset; 5 completion |
| FC2 positive overflow | PASS | Overflow/repeat/recovery; 4 completion |
| FC2 negative overflow | PASS | Overflow/repeat/recovery; 4 completion |
| VCD | PASS | Tám VCD không rỗng; waveform chính [golden_protocol.vcd](../build/phase2a/20261016_164656/golden_protocol.vcd) |
| Verilator lint | NOT RUN | Không tìm thấy executable trên PATH hoặc các thư mục tool đã kiểm tra |
| Icarus simulation | NOT RUN | Không tìm thấy iverilog/vvp; dùng Questa cho regression |
| Vivado synthesis/timing/utilization | NOT RUN | Chưa chạy synthesis/implementation; không có kết luận timing/DSP/BRAM đo thực tế |

**Mismatch còn lại: 0** trong các suite đã chạy. Tổng các MLP suite: 65 accepted = 39 successful + 14 expected-overflow completion + 12 reset-abort. Đây là số giao dịch regression, không phải số dòng dataset hay accuracy ML.

Scoreboard dùng so sánh `!==` bit-exact, không tolerance và không bỏ qua X. Kiểm tra cả 12 normalized, 8 pre-activation, 8 hidden, 4 logits, class, 12 normalization products, 8 FC1 sums và 4 FC2 sums. Mỗi trace phải xuất hiện đúng một lần. TB thay feature input sau acceptance và phát start pulse khi busy để kiểm tra snapshot/rejection. Reset được thử ở cả 12 state không-IDLE, mỗi lần có inference kiểm tra phục hồi. Các suite overflow có success ngay sau lỗi mà không reset, kiểm tra stale error/status bị xóa.

Fixture corner/overflow dùng model riêng **chỉ trong simulation** để đạt điểm số học khó và overflow ở đúng tầng. Expected values do reference Phase 1A tạo; expected rejection cũng được xác nhận bằng `OverflowError` của reference. Không sửa 14 golden cases hoặc model ECG để làm test pass. Source label và model class vẫn tách biệt; bốn class dự đoán được phủ nhờ toàn bộ golden package.

Cảnh báo runtime còn lại: `vopt-10587` do bật `+acc` để lưu waveform/quan sát hierarchy; một warning cho mỗi simulation. Không suppress warning và không coi đây là lỗi số học. Questa cũng in thông báo chuyển license variables ở phiên bản tương lai; không đổi license configuration. Lượt đầu có `13314` về implicit input-port kind; đã sửa bằng khai báo `input wire` tường minh và chạy lại. Cảnh báo Tcl `onerror` đã hết sau khi chuyển command vào macro `.do`.

## Cycle latency

Đếm từ rising edge nhận `start && ready` (t=0) đến rising edge đặt done. Thành công: **461 chu kỳ**, không phụ thuộc class/input hợp lệ. TB kiểm tra con số này trên mọi success, bao gồm recovery.

| Công đoạn | Chu kỳ |
|---|---:|
| Normalize: 12 × (REQ, MULT, ROUND) | 36 |
| FC1: 8 × (2 bias + 12×3 MAC + 1 round/ReLU) | 312 |
| FC2: 4 × (2 bias + 8×3 MAC + 1 round) | 108 |
| Argmax init + 3 compare + FINISH | 5 |
| Tổng | **461** |

Busy nhả khi done xuất hiện. Nếu đã rearm và payload sẵn sàng, edge tiếp theo có thể nhận inference mới: acceptance interval tối thiểu theo giao thức là 462 clocks. Testbench phát request kế tiếp ngay ở cơ hội đó.

Các overflow fixture cụ thể đo được: normalize **13** cycles, FC1 **76**, FC2 **376**. Đây là latency đến vị trí lỗi của fixture, không phải latency cố định của mọi input lỗi. Clock testbench 10 ns chỉ phục vụ mô phỏng logic; không chứng minh FPGA chạy 100 MHz. Tương tự, 461/50 MHz = 9,22 µs chỉ là quy đổi giả định nếu đạt timing 50 MHz, chưa phải kết quả hardware.

## Q12.20 và tradeoff tài nguyên

Giữ Q12.20 vì Phase 1A đã đo đủ miền, không clipping và 0 class mismatch so với float reference trên feature CSV. Việc giảm width cần audit lại sai số và vector, không được thay ngầm trong Phase 2A.

| Hạng mục | Phân tích kiến trúc, **chưa phải synthesis result** |
|---|---|
| ROM payload | 164×32 = 5.248 bit, gấp đôi 164×16 = 2.624 bit của package cũ |
| Hai cổng đọc 32 bit | Một RAMB18E1 TDP chỉ có tối đa 18 bit/port; RAMB36E1 hỗ trợ 36 bit/port. Mapping hợp lý là một RAMB36E1 hoặc hai RAMB18E1; synthesis có thể chọn layout/replication khác |
| Shared 33×32 multiply | Vượt multiplier 25×18 của một DSP48E1. Phân rã trực tiếp thành bốn partial products là một mốc ước lượng; số DSP thực tế tùy inference/optimization. Chia sẻ qua 140 phép nhân giúp tránh nhân bản theo neuron |
| Accumulator 68 bit | Vượt đường arithmetic 48 bit native của một DSP48E1; có thể cần carry logic hoặc nhiều DSP/adder segments |
| Register arrays | Snapshot + normalized + pre + hidden + logits chứa 1.408 bit logic; còn product/accumulator/FSM/trace. Đây không phải FF count sau optimization |
| Tốc độ/area | Core tuần tự ưu tiên ít multiplier; trả giá bằng 461 cycles. Một stage multiply 33×32 hoặc cộng/round rộng vẫn có thể cần pipeline thêm để đạt timing thực tế |

Thông số primitive lấy từ AMD: [DSP48E1 UG953](https://docs.amd.com/r/2024.1-English/ug953-vivado-7series-libraries/DSP48E1), [RAMB18E1 UG953](https://docs.amd.com/r/2021.1-English/ug953-vivado-7series-libraries/RAMB18E1), [RAMB36E1 UG953](https://docs.amd.com/r/2022.2-English/ug953-vivado-7series-libraries/RAMB36E1). Các dự đoán mapping trong bảng là suy luận từ width/cổng, không phải số liệu Vivado.

Nếu area cao: cân nhắc ROM một cổng (thêm chu kỳ lấy mean/inverse), bank dữ liệu, hoặc multiplier partial-product nhiều chu kỳ vẫn giữ đầy đủ precision. Nếu thay format/mixed precision, phải version lại contract và golden package. Chưa thực hiện các tối ưu đó. Reset asynchronous của datapath cũng có thể làm register nằm ngoài DSP; mapping và timing cần kiểm tra bằng synthesis sau này.

## Chạy lại và bằng chứng bất biến

Từ repository RTL trên branch ECG:

```powershell
python -B tools/run_ecg_rtl.py
# Hoặc chỉ xuất lại vector đã kiểm tra bằng reference:
python -B tools/export_ecg_sv_vectors.py
```

Có thể truyền `--questa-dir PATH`. Mỗi lần regression tạo thư mục build mới, không ghi đè VCD/test cũ. Exact commands tương đương `vlib`, `vmap -c`, `vmap work work`, `vlog -sv -lint`, `vopt`, rồi `vsim -c -onfinish stop -voptargs=+acc ... -do <macro>`. Runner kiểm tra exit code, error/fatal và PASS marker; lỗi compile không được báo thành simulation PASS. Compile order là package → ROM → core → TB. Training/Python deep-learning dependencies không cần cho regression này; dùng Python standard library và immutable Phase 1A reference.

Nếu cần thêm công cụ: Verilator có thể cài trong Ubuntu/WSL bằng `sudo apt-get update` rồi `sudo apt-get install verilator` ([hướng dẫn chính thức](https://verilator.org/guide/latest/install.html)); Icarus trong MSYS2 UCRT64 bằng `pacman -S --needed mingw-w64-ucrt-x86_64-iverilog` ([package chính thức](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-iverilog)). Chưa cài/chạy hai công cụ đó trong phase này.

[phase2a_integrity.json](phase2a_integrity.json) ghi so sánh SHA-256 với snapshot đầu phase, refs và working tree. Các file training, RTL cũ và Phase 1A giữ nguyên. Hai main refs giữ nguyên; chỉ thêm file trong repository RTL trên ECG. Không commit, push, merge hoặc kết nối datapath.

## Giới hạn và bước tiếp theo

Phase 2A chứng minh standalone RTL khớp hợp đồng fixed-point trên các suite đã nêu. Không chứng minh tính đúng đắn của preprocessing, nguồn gốc checkpoint, patient-disjoint accuracy, streaming peak detection hoặc model dùng lâm sàng. Các vấn đề Phase 1A vẫn tồn tại.

Chưa chạy Vivado để xác nhận device `xc7z020clg484-1`, BRAM/DSP inference, utilization hoặc WNS/TNS; chưa kiểm tra ROM file bị thiếu/corrupt trong một bitstream thật. ROM initialization là trách nhiệm build/package; regression hiện kiểm tra hash model trước khi compile. Error_stage=4 là cơ chế báo lỗi truy cập/control, không phải CRC nội dung ROM.

Bước nhỏ tiếp theo: review hợp đồng handshake/overflow và chạy standalone synthesis cho target ZC702 để đo mapping/timing, rồi mới quyết định tối ưu/pipeline. Việc ghép window/feature/APB/UART tiếp tục nằm ngoài slice này.
