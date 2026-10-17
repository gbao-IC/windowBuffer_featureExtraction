# Phase 3B — ECG Window Buffer signed16

Mô phỏng: 2026-10-16 theo log. Rà soát và hoàn tất báo cáo: **2026-10-17**. Repository RTL: branch `ECG`, HEAD `983f803b3e3d815a411c46da7ae66006a9d5af03` cộng working tree chưa commit. Training reference chỉ đọc: `AI_FSM_ECG@7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d`.

**PASS**: standalone frame storage, Questa lint/elaboration, năm simulation suites, kết nối qua Sample Interface Phase 3A và regression MLP Phase 2A. **FAIL**: tái hiện Window Buffer legacy không ghi mẫu cuối. **NOT RUN**: parity preprocessing ECG thật, FPGA synthesis/BRAM mapping/timing và Verilator. Phạm vi đã hoàn thành là lưu/đọc frame được nguồn chuẩn bị sẵn; chưa triển khai bộ chọn cửa sổ quanh beat hoặc resampler từ stream raw.

Đã đọc `AGENTS.md`, `docs/ECG_INTEGRATION_PLAN.md`, báo cáo Phase 1A–3A và đối chiếu trực tiếp `AI_FSM_ECG/create_dataset.py`. Giữ nguyên legacy window/top, Sample Interface, MLP, model, golden vectors và các báo cáo cũ. Không triển khai Feature Extraction, Master FSM hoặc UART.

## Training và boundary được chọn

Source training lấy cửa sổ `[beat_index - 250 : beat_index + 250)` trong tín hiệu 360 Hz: đúng **500 mẫu**, beat ở raw index 250, không có mẫu tại `beat_index + 250`. Cửa sổ vượt biên record bị bỏ. Sau đó gọi `scipy.signal.resample(win_360, int(500 * 250 / 360))`, cho **347 mẫu**. Tên 250 Hz là nominal; không thay bằng phép decimation hoặc divider. Theo lưới thời gian của phép resample này, raw index 250 nằm giữa output index 173 và 174; không tự gán một output sample làm R-peak chính xác.

Danh sách beat trước đó đã qua lọc annotation trong source. `rr_cur` lấy khoảng cách tới beat trước trong danh sách đã lọc, chia 360; `rr_prev` ban đầu 0,8 giây và chỉ cập nhật sau cửa sổ được chấp nhận. Beat trước trong danh sách và RR của cửa sổ được chấp nhận trước đó có thể khác nhau khi có cửa sổ bị bỏ. Buffer không tự suy ra các giá trị này từ số mẫu đã nhận.

Contract Phase 3B chọn điểm bắt đầu ở **frame đã chuẩn bị**, mặc định `FRAME_SAMPLES=347`. Replay/producer chịu trách nhiệm chọn đúng beat, resample, lượng tử hóa sang signed16 và gửi descriptor trước payload. Nếu nhiều beat có cửa sổ chồng nhau, producer gửi từng frame hoàn chỉnh, có thể lặp lại vùng mẫu chung. Buffer không áp đặt stride, overlap 50%, 512 mẫu hoặc phát hiện peak.

`FRAME_SAMPLES=500` được kiểm thử như cấu hình lưu 500 word nguyên trạng, nhằm kiểm tra addressing/counter. Cấu hình này không thực hiện 500→347 và không chứng minh preprocessing parity. `FRAME_SAMPLES=1` kiểm tra biên counter/address nhỏ nhất. Khi dùng module, chỉ đổi `FRAME_SAMPLES` dương và giữ các width theo giá trị mặc định suy ra từ N; các override width không nhất quán nằm ngoài contract.

Signed16 chỉ là container two's-complement **−32768…32767**. Chưa có raw ECG/annotation, physical units, gain/offset, scale hay quy tắc lượng tử hóa waveform phù hợp training. Không suy ra mV hoặc Q4.12 từ width. Toàn bộ waveform kiểm thử là tổng hợp; các endpoint ±signed16 cố ý kiểm tra storage, không đại diện biên độ bệnh nhân.

## Kiến trúc và frame ownership

[ecg_window_buffer.sv](../rtl/ecg/ecg_window_buffer.sv) dùng một bank RAM signed16, counter số mẫu, descriptor register và một response register cho đọc RAM. RAM/read-data register không reset; control chỉ cho đọc sau khi đã ghi đủ N địa chỉ, không lộ nội dung chưa khởi tạo. Control có một writer cho mỗi register. Thuộc tính `ram_style="block"` là yêu cầu inference; mapping thực tế chưa được synthesis xác nhận.

```text
descriptor accepted → CAPTURE đúng N mẫu → SEAL một clock → FULL
                                                        ↓
                                       read request / response, có stall
                                                        ↓
                                      release accepted → EMPTY

source_loss ở bất kỳ trạng thái nào → FAULT → flush sạch hoặc reset → EMPTY
```

Một bank đủ cho **Replay có thể dừng** và consumer chưa có deadline đã chốt. Khi FULL, producer bị backpressure đến khi consumer release; RAM không bị ghi đè. Payload RAM mặc định là 347×16 = **5.552 bit**, không phải utilization đo được. Ping-pong cần hai bank và descriptor/ownership cho mỗi bank; hiện chưa có yêu cầu ingest liên tục hoặc thời gian tiêu thụ frame để biện minh cho phần cứng này.

Thiết kế này không bảo đảm lossless cho nguồn không thể dừng. Trước khi nối nguồn live, cần biết khoảng cách giữa frame, mức chồng cửa sổ, tốc độ xuất frame đã resample, worst-case consumer stall và khả năng FIFO upstream. Hai bank cũng không bảo đảm không mất dữ liệu nếu consumer có thể stall vô hạn. Chưa triển khai ping-pong; đọc và ghi **được loại trừ theo phase**, test đồng thời xác nhận write bị chặn khi đang đọc FULL.

## Hợp đồng port và handshake

Một clock `clk`; tất cả input đồng bộ clock. Reset `rst_n` assert bất đồng bộ, release phải được caller đồng bộ; core không có CDC. Mọi handshake xảy ra tại rising edge khi valid và ready đều bằng 1. Ngoại trừ reset/flush/loss làm hủy giao dịch, producer phải giữ valid và payload ổn định khi bị stall.

| Nhóm port | Contract |
|---|---|
| `frame_start_valid/ready` | Chỉ nhận descriptor khi EMPTY. Không nhận descriptor thứ hai trong frame đang hoạt động. |
| `in_frame_id[31:0]` | ID opaque do nguồn cấp; caller chịu trách nhiệm quản lý thứ tự/uniqueness nếu cần. |
| `in_beat_index_360[31:0]` | Index beat trên timeline raw 360 Hz do nguồn cấp; phạm vi record do caller quản lý. |
| `in_rr_curr_ticks_360`, `in_rr_prev_ticks_360` | Unsigned32, đơn vị tick 1/360 giây. Với source training, previous RR khởi tạo 288 tick; producer phải áp dụng đúng quy tắc cập nhật đã nêu. |
| Metadata output cùng tên bỏ `in_` | Chụp nguyên tử tại descriptor handshake, giữ nguyên đến descriptor mới/reset; giữ lại cả khi release/abort để truy vết. Chỉ coi là frame hợp lệ khi `frame_valid=1`. |
| `sample_in`, `sample_valid/ready` | Signed16; nhận ở CAPTURE. Mỗi edge valid&&ready ghi một word, kể cả valid cao liên tục. |
| `samples_collected` | Số mẫu đã nhận, 0…N; bao gồm mẫu cuối. Xóa khi release/flush/loss/reset. |
| `frame_valid` | Level báo đủ N mẫu và đã qua SEAL; giữ đến release/abort. Không phải pulse. |
| `frame_release_valid/ready` | Consumer trả ownership sau khi đọc xong; chỉ nhận khi FULL và không còn response pending. |
| `rd_req_valid/ready`, `rd_req_addr` | Đọc địa chỉ ngẫu nhiên trong frame FULL; địa chỉ 0 là mẫu nhận đầu tiên, N−1 là mẫu cuối. Chỉ một response outstanding. |
| `rd_rsp_valid/ready`, `rd_rsp_data`, `rd_rsp_addr` | Response đọc đồng bộ, signed16 và địa chỉ echo. Giữ cả data/address/error khi consumer stall. |
| `rd_rsp_error` | Địa chỉ N trở lên trong miền address bus trả error=1 và data=0, không đọc RAM ngoài miền; frame vẫn hợp lệ. Chỉ đọc error/address khi response valid. |
| `source_loss` | Sự kiện mất mẫu upstream; nối `overflow_pulse` của Phase 3A, không nối sticky `overflow_flag`. Có thể tie 0 cho Replay đúng ready/valid và không mất dữ liệu. |
| `fault`, `loss_flag` | FAULT và cờ lỗi sticky đến flush sạch/reset; đóng mọi handshake. Không tự phục hồi chỉ vì `source_loss` hạ. |
| `frame_abort` | Pulse một clock khi loss/flush hủy CAPTURE/SEAL/FULL. Loss khi EMPTY vẫn vào FAULT nhưng không có frame để abort. |
| `flush` | Hủy frame/response, xóa fault/loss và trở về EMPTY ở edge. Loss có ưu tiên cao hơn flush; chỉ flush khi loss đã hết mới phục hồi. |

RR metadata được vận chuyển bit-exact, không tính RR feature, kiểm tra tính hợp lý sinh lý hoặc chia cho 360 trong module này. Frame ID/beat index/RR có width32 nên caller phải quản lý phạm vi và record boundary. Chưa có annotation symbol hoặc class label trong buffer; chúng không được suy ra từ payload.

Descriptor phải được nhận trước mẫu đầu tiên tại boundary buffer. **Đúng N sample handshake** định nghĩa frame end; không có `sample_last`, timeout hoặc padding tự động. N−1 mẫu sẽ chờ vô hạn cho mẫu cuối hoặc flush/loss. Buffer không thể phát hiện mẫu bị mất/nhân đôi trước boundary nếu nguồn không báo lỗi. Mẫu thừa khi FULL bị stall, không ghi vào frame hiện tại; producer phải gắn nó với descriptor tiếp theo hoặc hủy offer bằng quy trình flush. Không được dựa vào buffer để sửa framing sai của producer.

## Latency và backpressure

| Sự kiện | Latency/hành vi đã kiểm tra |
|---|---|
| Descriptor nhận tại edge D | CAPTURE có hiệu lực sau D; mẫu đầu sớm nhất nhận ở D+1. |
| Capture liên tục | Một mẫu/clock, không divider; N handshake ghi đủ địa chỉ 0…N−1. |
| Mẫu cuối nhận tại edge L | Ghi RAM ngay tại L, counter=N, vào SEAL; `frame_valid` lên sau L+1 nếu không loss/flush. |
| Đọc đầu tiên | Sớm nhất nhận request tại L+2, sau khi FULL đã hiện hữu. |
| Read request nhận tại edge R | RAM/response register cập nhật sau R, consumer sớm nhất nhận tại R+1: **read latency một clock**, không đường đọc tổ hợp. |
| Read liên tiếp | Có thể consume response cũ và nhận request mới cùng edge; một response/clock nếu consumer luôn ready. |
| Response stall | Data/address/error/valid giữ ổn định; `rd_req_ready=0` khi slot đầy và consumer không ready. |
| Release trong lúc có response | Ready thấp đến khi response đã được consume; release được nhận sớm nhất ở edge kế tiếp. Không âm thầm bỏ response. |
| Release và read cùng được yêu cầu | Release-valid chặn nhận read mới để có thể drain/release; không đọc và giải phóng cùng một frame ở cùng edge. |
| Full buffer / producer tiếp tục offer | `sample_ready=0`; legal stall không phải overflow. |

Latency frame tổng phụ thuộc cadence mẫu và downstream stall, không có upper bound khi caller được phép dừng. Clock TB là 20 ns để mô phỏng; đây không phải bằng chứng thiết kế đạt timing 50 MHz trên XC7Z020.

## Loss, reset và recovery

`source_loss` chặn ngay visible ready/valid, rồi tại edge đưa state vào FAULT, xóa count và response pending. Nếu frame đang capture, seal hoặc đã publish thì frame đó bị hủy. Policy bảo thủ cũng hủy FULL khi lỗi có thể thuộc dữ liệu đến sau: chưa có event ID để phân biệt lỗi thuộc frame nào.

SEAL thêm một clock nhằm chặn publication khi Phase 3A báo loss qua pulse register từ edge nhận cuối. Đây không phải bảo đảm đối với một adapter có độ trễ báo loss tùy ý. Nếu loss xuất hiện sau khi consumer đã đọc một phần frame, consumer phải bỏ toàn bộ kết quả tạm của frame đó khi thấy `fault/frame_abort`. Không thể thu hồi một kết quả đã được consumer commit ngoài contract.

Replay ready/valid không mất mẫu khi buffer đầy. Với wrapper pulse Phase 3A, một sample có thể còn pending ở upstream; sample đến thêm khi slot đó full bị drop-new và phát overflow pulse. Test tích hợp pulse tạo loss thật theo cách này và xác nhận Window vào FAULT. Không có silent overwrite hoặc tiếp tục đếm để ghép mẫu từ hai frame.

Recovery phải được caller điều phối: dừng nguồn, bỏ phần còn lại của frame lỗi, xóa pending sample ở upstream, flush buffer khi `source_loss=0`, rồi cấp descriptor và payload mới. **Flush Window riêng lẻ không xóa được mẫu cũ đang nằm trong Sample Interface.** Trong TB tích hợp, caller đồng thời assert reset cho front-end khi flush; đó là stimulus kiểm thử, chưa phải reset/CDC architecture sản phẩm.

Reset xóa control/descriptor/status/response-valid về 0, abort frame đang hoạt động, không phát abort pulse sau reset và không reset nội dung RAM. Frame mới phải ghi đủ N mẫu trước khi đọc, nên RAM cũ không thể được xuất thành frame mới. Test có reset giữa clock lúc capture dở và lúc response đang stall, rồi kiểm tra phục hồi.

## Kết quả thực chạy

Lệnh: `python -B tools/run_ecg_window_tests.py`, exit **0**. Tool QuestaSim-64 **2024.1**, compiler/simulator 2024.02 tại `C:/MentorGraphics/win64`. [phase3b_results.json](phase3b_results.json) lưu exact commands, return codes, source hashes, markers và log/VCD paths. Lượt chạy: [build/phase3b/20261016_224152_083607](../build/phase3b/20261016_224152_083607).

| Diagnostic | Kết quả | Bằng chứng |
|---|---|---|
| Questa `vlog -sv -lint` và `vopt` Window top | **PASS** | 0 errors, 0 warnings; compile cùng hai module Phase 3A và TB mới. |
| Window 347, direct source | **PASS** | 12 descriptor, 3.989 writes, 2.432 read requests, 2.430 responses; 0 mismatch. |
| Window 500, transport-only | **PASS** | 12 descriptor, 5.749 writes, 3.503 requests, 3.501 responses; 0 mismatch. |
| Window 1, parameter boundary | **PASS** | 12 descriptor, 10 writes, 10 requests, 8 responses; 0 mismatch. |
| Phase 3A Replay → Window 347 | **PASS** | 12 descriptor, 3.988 writes, 2.432 requests, 2.430 responses; 0 mismatch. |
| Phase 3A pulse → Window 347 | **PASS** | 13 descriptor, 4.335 writes, 2.432 requests, 2.430 responses; thêm loss thật từ pulse adapter; 0 mismatch. |
| First/last sample, order, signed values | **PASS** | Mỗi suite đọc đúng first/last bảy lần; forward/reverse reads. N>1 có min/max signed16 và dữ liệu âm/dương; N=1 dùng cùng word 32767 cho cả first/last. |
| Read/write cùng được offer | **PASS** | Direct 347 có 695 read handshake khi write đang bị chặn; không có simultaneous accepted write/read trong một bank. |
| Read response backpressure | **PASS** | Direct 347 có 1.719 stalled-response cycles; valid/data/address/error giữ nguyên. |
| Full/partial/loss/reset/recovery | **PASS** | N−1 không publish, loss ở CAPTURE/SEAL/FULL/pending response, loss ưu tiên flush, reset capture/response, frame mới sau recovery. |
| Legacy last sample | **FAIL** | `FAIL LEGACY_WINDOW_LAST expected=a5/count512 actual=xx/count511`. Giữ nguyên source legacy. |
| VCD | **PASS** | Năm window VCD và một legacy VCD không rỗng. |
| Phase 3A Sample Interface regression | **PASS** | Hai suites, mỗi suite quét 65.536 signed16 encodings, random/stall/reset/overflow; 0 mismatch. |
| Phase 2A MLP regression | **PASS** | Tám suites, 14/14 golden cases, class mask `0xF`, 0 mismatch; success 461 cycles không đổi. |
| Verilator lint / Icarus | **NOT RUN** | Không có executable khả dụng theo runner; Questa là simulator đã chạy. Không cài phần mềm. |
| Vivado synthesis, BRAM mapping, timing, CDC/board | **NOT RUN** | Không chạy hardware flow trong Phase 3B. Không có utilization/WNS/TNS mới. |
| Raw ECG preprocessing / signed16 quantization parity | **NOT RUN** | Thiếu raw ECG, annotation, mapping biên độ và contract lượng tử hóa. |

Mỗi suite có hai read requests bị hủy có chủ đích: một bởi loss và một bởi reset khi response pending. Vì vậy `requests = responses + 2`; đây không phải hai mismatch. Sáu frame/suite được release thành công. Bộ đếm `aborted=4` (pulse là 5) trong log đếm loss/flush hủy frame; hai reset-abort được kiểm tra riêng, không nằm trong counter này. Số writes có thể khác một word giữa direct/link do reset chủ đích xóa sample đang pending ở front-end.

Scoreboard dùng ordered queue các mẫu được buffer nhận và queue response độc lập, so sánh `!==`, kiểm tra count, descriptor association, valid/latency ở từng edge, read-before-complete, invalid address, release khi response pending và không xuất dữ liệu stale sau reset/loss. Random backpressure dùng seed `0x3b347500`. Đây là functional checks/counters, không phải formal proof hoặc UCDB coverage. Không force state hoặc RAM DUT.

Legacy Window có nhánh xử lý cuối frame trước nhánh ghi RAM, nên sample cuối không được ghi; counter giữ 511. Runner giữ diagnostic **FAIL**, `expected_baseline_failure=true`, tách khỏi gate implementation mới. Regression con cũng giữ lỗi ADC legacy ba mẫu→một mẫu từ Phase 3A. Không coi legacy top/window/ADC là đã sửa hoặc PASS.

Questa có warning runtime `vopt-10587` do `+acc`, một warning mỗi simulation, giữ nguyên trong log. Trường `errors` của JSON chứa các dòng log có từ Error/Fatal/FAIL, gồm cả `Errors: 0`; không được hiểu độ dài mảng đó là số lỗi compiler. Gate kiểm tra riêng exit code, `** Error`, `** Fatal`, FAIL và required PASS marker. Với legacy `$fatal`, process có thể thoát 0 qua macro Tcl nhưng diagnostic vẫn là **FAIL**.

Waveforms: [window347.vcd](../build/phase3b/20261016_224152_083607/window347.vcd), [replay_window347.vcd](../build/phase3b/20261016_224152_083607/replay_window347.vcd), [pulse_window347.vcd](../build/phase3b/20261016_224152_083607/pulse_window347.vcd). VCD ghi interface/control cần thiết; không dump toàn bộ RAM/scoreboard queue.

## Rà soát bằng chứng ngày 2026-10-17

Lượt tiếp tục chỉ đọc source/kết quả đã có và hoàn tất tài liệu. Không sửa RTL, TB, runner hoặc golden; không chạy lại simulation đã PASS và không bắt đầu Phase 3C. `git diff` và staged diff đều rỗng; các file Phase 3B là file mới chưa tracked, nên được kiểm tra trực tiếp và đối chiếu hash, không dựa riêng vào diff rỗng.

[phase3b_review.json](phase3b_review.json) ghi **PASS** cho đối chiếu 21 source/artifact đầu vào với hash được lưu trong ba regression summaries; kiểm tra sự tồn tại, log markers, exit codes và kích thước VCD của 62 artifacts; đồng thời lưu SHA-256 hiện tại của các artifacts đó. Hash log/VCD được thu thập tại lần review này, không được trình bày thành hash đã lưu từ đầu simulation. Toàn bộ 17 VCD của window/legacy, sample/legacy và MLP còn tồn tại và đúng kích thước đã ghi.

Đã đọc trực tiếp các event trong sáu VCD Phase 3B, ngoài việc kiểm tra file không rỗng:

- **Legacy FAIL xác nhận**: 512 rising edges có input valid sau reset; input cuối `0xA5`; địa chỉ đọc 511; counter cuối 511; output tám bit `xxxxxxxx` tại cuối waveform 10.340 ns. Khớp `$fatal` trong [legacy_last_sample.log](../build/phase3b/20261016_224152_083607/legacy_last_sample.log), không phải thiếu stimulus mẫu thứ 512.
- **Năm suite mới PASS**: mọi lần `frame_valid` lên đều có count=N; first/last sample khớp payload mong đợi bảy lần/suite. Số response handshake đọc từ VCD lần lượt 2.430 / 3.501 / 8 / 2.430 / 2.430, khớp log scoreboard. Có 9 published frames/suite, riêng pulse có 10 do thêm tình huống overflow; một số published frames bị hủy có chủ đích, không phải tất cả đều release thành công.
- **Không cần regression bổ sung**: tất cả source hash vẫn khớp lần simulation PASS và không phát hiện mismatch mới trong review. Regression chạy lại ở lượt tiếp tục: **NOT RUN**, do không có thay đổi chức năng hoặc bằng chứng lỗi mới cần xác minh.

## Regression và bảo toàn workspace

Window runner gọi runner Phase 3A nguyên trạng sau khi năm suite mới PASS. Lượt sample mới: [build/phase3a/20261016_224253_040119](../build/phase3a/20261016_224253_040119), [summary mới](phase3a_results_20261016_224253_040119.json). Replay: 69.303 accepted, 69.302 delivered, 1 reset-abort; pulse: 68.860 accepted, 68.859 delivered, 1 reset-abort, 1.700 loss được kiểm tra đúng.

MLP được runner Phase 3A chạy một lần với summary riêng: [mlp_results.json](../build/phase3a/20261016_224253_040119/mlp_results.json), [log/VCD](../build/phase2a/20261016_224321). Arithmetic 180 cases; ROM 164 địa chỉ mỗi cổng; golden/protocol, signed corners và bốn overflow suites đều PASS. Tổng vẫn 65 accepted = 39 success + 14 expected-overflow completions + 12 reset-aborts. Không chạy lại audit toàn dataset hoặc huấn luyện.

[phase3b_integrity.json](phase3b_integrity.json) đối chiếu snapshot đầu phase: **128/128 file đã có giữ nguyên SHA-256**, gồm training, RTL legacy/mới của phase trước, model, golden vectors, tests và báo cáo/kết quả cũ. Không sửa bất kỳ file source có trước Phase 3B. Các run log/VCD mới nằm trong thư mục build mới; không ghi đè run cũ.

| Repository | Branch / HEAD | Main ref / trạng thái |
|---|---|---|
| `AI_FSM_ECG` | `main` / `7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d` | Main cùng SHA; working tree sạch, chỉ đọc. |
| `windowBuffer_featureExtraction` | `ECG` / `983f803b3e3d815a411c46da7ae66006a9d5af03` | Main giữ `9e33a48dab0d5d517ac8adaf4000dca9f8342cda`; các file phase trước và phase mới chưa commit. |

Remotes giữ nguyên `https://github.com/gbao-IC/AI_FSM_ECG.git` và `https://github.com/gbao-IC/windowBuffer_featureExtraction.git`. Không checkout/fetch/commit/push/merge hoặc xóa file.

## File mới và tái lập

| File mới | Vai trò |
|---|---|
| [rtl/ecg/ecg_window_buffer.sv](../rtl/ecg/ecg_window_buffer.sv) | Core frame storage authoritative, signed16, descriptor, synchronous read, backpressure và abort/recovery. |
| [tb/ecg/tb_ecg_window_buffer.sv](../tb/ecg/tb_ecg_window_buffer.sv) | Năm cấu hình self-checking; standalone và kết nối Phase 3A. |
| [tb/ecg/tb_legacy_window_last.sv](../tb/ecg/tb_legacy_window_last.sv) | Tái hiện lỗi last sample/count của legacy. |
| [tools/run_ecg_window_tests.py](../tools/run_ecg_window_tests.py) | Guard branch, lint/elaboration, simulations, logs/VCD, nested regression và hash source. |
| `docs/phase3b_report.md`, `docs/phase3b_results.json`, `docs/phase3b_review.json`, `docs/phase3b_integrity.json` | Contract, bằng chứng thực chạy, review log/VCD/hash và kiểm tra bất biến. |
| `docs/phase3a_results_20261016_224253_040119.json` | Summary mới của regression Phase 3A, giữ mọi summary cũ. |
| `build/phase3b/...`, `build/phase3a/20261016_224253_040119`, `build/phase2a/20261016_224321` | Snapshot, log, macro, simulator work và VCD mới; build đã được ignore từ phase trước. |

Từ repository RTL trên branch ECG:

```powershell
python -B tools/run_ecg_window_tests.py
# Nếu cần chọn Questa đã cài:
python -B tools/run_ecg_window_tests.py --questa-dir C:/MentorGraphics/win64
```

Mỗi lần chạy tạo build directory và summary mới. Không cần dataset, Python ML dependencies hoặc thay golden package để chạy các suite này. Compile list window chỉ gồm hai module Sample Interface Phase 3A, Window mới và TB; legacy được compile/test riêng để tái hiện lỗi, không nối vào datapath mới.

## Yêu cầu tích hợp còn mở

Trước khi triển khai Feature Extraction hoặc gọi demo là raw-ECG end-to-end, cần chốt nguồn beat/annotation và RR; waveform units/scale/quantization signed16; cách tạo đúng Fourier-resampled 347 mẫu; record boundary; delay/loss metadata; flush đồng bộ giữa producer, Sample Interface và consumer; và thời gian giữ/đọc frame để quyết định FIFO/ping-pong. Nếu cấp beat/RR từ annotation thì demo phải ghi rõ **oracle-assisted**, không phải tự phát hiện beat streaming.

Window hiện tại chứng minh storage và giao thức trên mẫu tổng hợp, chưa xác nhận preprocessing tương đương training. Các vấn đề provenance checkpoint, patient overlap và raw data của Phase 1A vẫn giữ nguyên. Chưa sửa thuật toán hoặc thêm Feature Extraction/Master FSM/UART để vượt qua các quyết định chưa được chốt.
