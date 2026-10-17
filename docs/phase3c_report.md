# Phase 3C — ECG Feature Extraction trên frame signed16

Ngày: **2026-10-17**. RTL branch `ECG`, HEAD `983f803b3e3d815a411c46da7ae66006a9d5af03`; training chỉ đọc tại `7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d`.

**PASS** cho engine standalone tính đủ **12 feature** theo hợp đồng số nguyên signed16 đã công bố: lint/elaboration, arithmetic unit, 28 golden frames × 12 outputs ở cả hai chế độ direct/stalled, lỗi đọc, abort/reset/recovery và regression Window/Sample/MLP. **FAIL** cho yêu cầu bit identity với phép tính NumPy float32 trên cùng các số nguyên tổng hợp; đây là hai hợp đồng precision khác nhau. **NOT RUN** cho preprocessing ECG raw, nối vào MLP, FPGA synthesis/resource/timing. Không tuyên bố đạt đầy đủ gate Feature Extraction của integration plan trên dữ liệu bệnh nhân.

Đã đọc `AGENTS.md`, integration plan, báo cáo Phase 1A–3B, `tools/ecg_reference.py`, các kiểm thử reference hiện có và source authoritative `../AI_FSM_ECG/create_dataset.py`. Snapshot đầu phase gồm 137 file. Chỉ thêm file Phase 3C; toàn bộ training, RTL các phase trước, legacy, model, normalization và golden package cũ giữ nguyên nội dung.

## Công thức, thứ tự và nguồn metadata

Training cắt 500 mẫu `[beat−250:beat+250)` tại 360 Hz, rồi Fourier-resample bằng SciPy thành 347 mẫu nominal 250 Hz. Engine này bắt đầu ở **347 mẫu đã chuẩn bị trong Window Phase 3B**. Không chọn beat, resample, lọc hoặc áp overlap mới.

Ký hiệu N=347, x là giá trị tín hiệu, ε=1e−9; h1 là x[0:173], h2 là x[173:347]. Trong hợp đồng kiểm chứng Phase 3C, **x là chính giá trị integer signed16**, đơn vị count chưa được gán với mV hoặc đơn vị training. Nếu giá trị waveform training bằng a×count thì RMS/peak/ptp/max đổi theo a, variance theo a²; epsilon trong các tỷ số cũng chịu ảnh hưởng của miền đơn vị. Không được nối trực tiếp output này vào scaler đã huấn luyện khi chưa chốt a/offset/quantization.

| Index | Feature | Công thức training | Đơn vị |
|---:|---|---|---|
| 0 | `f_rms` | sqrt(mean(x²)) | Biên độ |
| 1 | `f_var` | mean((x−mean(x))²), population variance | Biên độ² |
| 2 | `f_peak` | max(abs(x)) | Biên độ |
| 3 | `f_zc` | số cặp liên tiếp có sign khác nhau / **347** | Không thứ nguyên |
| 4 | `f_ptp` | max(x)−min(x) | Biên độ |
| 5 | `f_crest` | clip(peak/(rms+ε), **0,15**) | Tỷ số biên độ |
| 6 | `f_half_ratio` | rms(h1)/(rms(h2)+ε), không clip | Tỷ số biên độ |
| 7 | `f_max` | max(x), giữ dấu | Biên độ |
| 8 | `f_rr` | rr_current_ticks / **360** | Giây |
| 9 | `f_rr_prev` | rr_previous_ticks / **360** | Giây |
| 10 | `f_rr_ratio` | rr_current_seconds/(rr_previous_seconds+ε) | Không thứ nguyên |
| 11 | `f_rr_diff` | rr_current_seconds−rr_previous_seconds | Giây, **có dấu** |

Sign có ba giá trị −1/0/+1: −→0 và 0→+ là hai thay đổi; 0→0 không tăng count. Không dùng riêng phép XOR sign bit. Half-window chia **173/174**, không 173/173 hoặc 174/173. Chú thích training gọi RR difference là độ lệch tuyệt đối nhưng phép tính thực tế là hiệu có dấu; RTL theo phép tính.

Hai RR field lấy từ descriptor Phase 3B, unsigned32 tick của timeline **360 Hz**, snapshot cùng frame ID/beat index ở start handshake. Không tính RR từ 347 mẫu hoặc chia tick cho 250. Training khởi tạo previous RR=0,8 giây (288 tick), current RR dựa vào beat trước trong danh sách annotation đã lọc, previous RR chỉ cập nhật sau cửa sổ được chấp nhận; trách nhiệm cung cấp đúng metadata thuộc producer.

Test arithmetic chấp nhận RR tick 0…2³²−1, gồm zero/zero và previous=0 để kiểm tra epsilon. Đây là robustness contract, không tuyên bố các descriptor đó là beat hợp lệ trong dataset; dataset builder bỏ current RR≤0. Engine không tự điền RR mặc định, chặn giá trị phi sinh lý hoặc tính class label.

## Hợp đồng fixed-point và implementation

[phase3c_numeric_contract.md](phase3c_numeric_contract.md) được viết trước RTL, định nghĩa `signed16-counts_f48-roots_signed96-f32_v1`. Output 12 word **signed96, F=32**, gọi Q64.32 với sign nằm trong 64 bit nguyên, miền [−2⁶³, 2⁶³−2⁻³²]. Đây là interface riêng cho feature arithmetic; **không phải** interface signed32 Q12.20 của MLP.

| Đại lượng | Width/miền cần thiết và cách xử lý |
|---|---|
| Mẫu và magnitude | Input signed16; sign-extend lên signed17 trước abs để `abs(−32768)=32768`, lưu peak unsigned16. |
| Bình phương | Nhân magnitude17×17 ra unsigned34, lấy 32 bit sau chứng minh x²≤2³⁰. Không nhân trong cast có thể thu hẹp width biểu thức. |
| Sum | Signed25: |sum|≤11.370.496. |
| Sum squares | Unsigned39: ≤347×2³⁰. Hai half sums unsigned38, tối đa 174×2³⁰. |
| Variance | `(347*T−S²)/347²`; numerator không âm, vừa unsigned48. Tích |S|² giữ đủ 50 bit, không dùng variance sample hoặc trừ các mean đã lượng tử hóa. |
| ZC/ptp/max | Count unsigned9, max346; ptp unsigned17, max65535; max signed16. |
| RMS nội bộ | RNE(sqrt(T/n)×2⁴⁸), n=347/173/174. Root lưu unsigned96, miền thực tế tối đa32768×2⁴⁸. |
| Output rounding | Nearest, ties-to-even; RR difference round magnitude rồi trả dấu. RMS F48 round về F32. |
| Division/sqrt | Khối tuần tự unsigned192; trial remainder193; floor divide192 cycles, floor sqrt96 cycles; không dùng `/`, `real` hoặc `$sqrt` trong RTL. |
| Epsilon | Giữ **chính xác 1/10⁹** bằng tử/mẫu nguyên, không lượng tử hóa epsilon thành0. |
| Saturation/range | Chỉ crest clip đúng0…15. Các output khác không clamp. Range/math error hủy result với error_code3. |

Căn dùng hai remainder: chia `T<<96` cho n, lấy integer sqrt của quotient, rồi so sánh midpoint với cả division remainder và sqrt remainder để RNE đúng căn của phân số. Không chỉ lấy sqrt của một mean đã bị cắt integer. Chia tính floor quotient/remainder, so sánh 2×remainder với denominator để làm tròn.

Với roots F48 U,V,W, crest chia `peak×10⁹×2⁸⁰ / (U×10⁹+2⁴⁸)`; half ratio chia `V×10⁹×2³² / (W×10⁹+2⁴⁸)`; RR ratio chia `current_ticks×10⁹×2³² / (previous_ticks×10⁹+360)`. Công thức encoded đầy đủ nằm trong contract và Python reference.

Miền output lớn nhất đáng chú ý: RMS/peak≤32768; variance≤65535²/4; ZC≤346/347; ptp≤65535; crest≤15; half ratio≤32768×10⁹; RR seconds≤(2³²−1)/360; RR ratio≤(2³²−1)×10⁹/360 ≈1,193×10¹⁶; RR difference có cả hai dấu. Q64.32 chứa toàn bộ miền này. Các bound được suy từ input contract, không suy ra từ dataset feature CSV.

Khối192 bit ưu tiên hợp đồng rõ ràng và dễ kiểm chứng, chưa tối ưu area/timing. Có phép nhân sample, phép nhân sum², arithmetic rộng và các nhân constant; iteration giảm việc triển khai divider tổ hợp nhưng không chứng minh đường subtract/compare192 bit đạt20 ns. LUT/FF/DSP/BRAM, WNS/TNS: **NOT RUN**. Không đổi format của MLP để khớp engine này.

## Window handshake, ownership và lỗi

`ecg_feature_core` là FSM nội bộ của engine, không phải Master FSM hệ thống. Một frame đang xử lý; không có queue request hoặc CDC. Reset active-low asynchronous, reset release phải được caller đồng bộ.

| Giao dịch | Hành vi |
|---|---|
| `start && start_ready` | Chỉ nhận khi IDLE và Window frame_valid, không fault/abort. Chụp ID, beat index, hai RR tick; xóa result/error cũ. |
| Read request | Địa chỉ0…346; một request outstanding. Giữ valid/address khi request bị stall. |
| Read response | Chỉ consume ở WAIT_RSP khi valid&&ready; kiểm tra address echo và error. Dùng đúng synchronous response một clock của Window, đồng thời chấp nhận response bị trì hoãn. |
| `result_valid/result_ready` | Toàn bộ12 feature và metadata ổn định khi stall. Window vẫn được giữ; producer chưa được ghi frame tiếp theo. |
| `done` thành công | Pulse tại edge consumer nhận result, không phát chỉ vì result vừa tính xong. |
| Release | Sau result handshake, phát Window release-valid, chờ release-ready rồi trở về IDLE. Không release khi còn read response outstanding. |
| Start khi busy | Không nhận, không queue. Producer muốn giao dịch sau phải giữ/đưa request ở lúc ready theo ready/valid. |
| Abort/frame fault/frame abort/frame_valid mất | Hủy computation hoặc result chưa nhận, done pulse lỗi, error_code1, vào FAULT. Các read/result valid bị chặn. |
| Read error hoặc sai địa chỉ | error_code2, done pulse lỗi, vào FAULT. Không tiếp tục cộng mẫu để tạo frame giả. |
| Math/range/control error | error_code3, done pulse lỗi, vào FAULT. Output không valid; không wrap/saturate để tiếp tục. |
| `flush_required` | High ở FAULT. Caller phải flush Window và pending response, ngừng nguồn; engine chờ quan sát frame không valid và fault/abort đã clear. |
| Reset | Xóa control, features, metadata/error; abort không phát done. Reset phải phối hợp với Window để bỏ ownership/response cũ. |

Loss/abort là ngoại lệ cho quy tắc giữ result khi stall. Consumer phải bỏ kết quả chưa handshake nếu frame bị revoke. Sau result đã handshake, lỗi xảy ra trong chu kỳ release có thể yêu cầu flush nhưng không phát done thứ hai; không thể thu hồi result đã được consumer nhận. Chính sách commit downstream cần giữ boundary này khi tích hợp. Các debug/feature register chỉ có nghĩa như một result hoàn chỉnh khi result_valid=1.

## Golden reference và precision audit

[ecg_feature_reference.py](../tools/ecg_feature_reference.py) có hai oracle độc lập về số học: Fraction/integer/isqrt với kiểm tra midpoint chính xác, và Decimal100 digits dùng square root cùng mean-centered variance. Oracle Decimal không mô phỏng divider/sqrt RTL. Cả hai lượng tử hóa đúng contract F48/F32 và khớp bit-exact trên28 golden frames cùng100 random frames trong Python tests.

Golden mới được sinh trong build riêng: [features.json](../build/phase3c/20261017_081043_552454/vectors/features.json), `samples.mem`, `rr.mem`, `expected.mem`, `math.mem`. JSON có từng frame signed16, hai RR tick, statistics, roots F48, 12 encoded words, giá trị Decimal lý tưởng và sai số. Không sửa `tests/vectors/ecg_golden.json`, model hoặc bất kỳ vector Phase 1A/2A nào. Hash các input/vector được runner ghi trong summary; vector giữa lượt FAIL và PASS giống byte-for-byte.

| Feature | Max absolute error fixed so với công thức Decimal lý tưởng trên28 frame |
|---|---:|
| RMS | 1,071904×10⁻¹⁰ |
| Population variance | 1,116769×10⁻¹⁰ |
| Peak | 0 |
| ZC/N | 1,080281×10⁻¹⁰ |
| Peak-to-peak | 0 |
| Crest clipped | 1,095803×10⁻¹⁰ |
| Half ratio | **8,618497×10⁻⁷** |
| Signed max | 0 |
| RR current | 8,795825×10⁻¹¹ |
| RR previous | 1,138284×10⁻¹⁰ |
| RR ratio | 1,054753×10⁻¹⁰ |
| Signed RR difference | 8,795825×10⁻¹¹ |

Ngân sách regression trước chạy: half ratio2×10⁻⁶; các feature khác1,17×10⁻¹⁰. **PASS** trên golden cases. Half ratio có denominator epsilon khi nửa sau bằng0, nên sai số căn F48 được nhân lên tới10⁹; vì vậy không thể dùng cùng absolute tolerance với feature khác. So sánh RTL↔fixed oracle vẫn **0 LSB tolerance** cho cả12 feature.

Function training được lấy riêng qua AST và chạy trên cùng giá trị integer cast sang float64:28/28 cases khớp công thức độc lập theo `rel_tol=2e-14`, `abs_tol=1e-12`. Không import/chạy phần tạo dataset hoặc training. Reference float Phase1A cũng được đối chiếu trên các RR dương mà nó hỗ trợ. Kết quả này chứng minh công thức/feature order trên input đã định nghĩa, không chứng minh nguồn preprocessing.

[phase3c_precision.json](phase3c_precision.json) ghi khác biệt khi chạy chính function đó với **NumPy float32**. Bit identity so với công thức count lý tưởng: **FAIL**. Max abs difference quan sát gồm RMS≈0,001444737, variance≈171,067263 count², crest≈1,273×10⁻⁷, half ratio≈264.815,556 trên tỷ số rất lớn. RR dùng scalar Python nên vẫn có sai số biểu diễn binary64; Decimal/rational reference không giả vờ tái hiện mọi bit của NumPy. Không dùng các chênh lệch này để kết luận accuracy model.

Native training load float32 và resample bằng SciPy; các bước mean/variance/sqrt có rounding riêng. Engine hiện thực công thức toán học với precision được công bố, không pipeline IEEE float32 bit-exact. Raw ECG/annotation, waveform quantization, scale/offset và representative source windows chưa có: **training preprocessing parity NOT RUN**. Không đo classification accuracy từ các frame tổng hợp.

## Kết quả thực chạy và latency

Lượt cuối: [build/phase3c/20261017_081043_552454](../build/phase3c/20261017_081043_552454). Summary chính của lượt PASS: [phase3c_results_20261017_081043_552454.json](phase3c_results_20261017_081043_552454.json). `docs/phase3c_results.json` giữ lượt FAIL đầu tiên, không được hiểu là kết quả mới nhất.

| Diagnostic | Kết quả | Bằng chứng |
|---|---|---|
| Python reference tests | **PASS** | 8/8 tests, không skip; hand cases, signed rounding, input rejection,100 random oracle comparisons, Phase1A/AST training function parity. |
| Golden generation | **PASS** | 28 frames, đủ12 features; independent Decimal parity và error budget. |
| Questa `vlog -sv -lint`, `vopt` core | **PASS** | 0 errors,0 warnings compile/elaboration. |
| Arithmetic unit | **PASS** | 149 cases: divide192/sqrt96, full192-bit endpoints/random, divide-by-zero, abort/reset/recovery. |
| Feature + Window direct | **PASS** | 28 golden +2 repeat/recovery thành công;5 expected faults;3 reset-aborts;38 accepted;0 mismatch. |
| Feature + Window stalled | **PASS** | Cùng coverage số học;3.955 request-stall và3.987 response-stall cycles;510 output-stall cycles;0 mismatch. |
| First/last, zeros, signed16 extremes | **PASS** | Hai impulse ở đầu/cuối, full min/max, âm/dương, constant/zero, zero transitions, boundary172/173, half-zero. |
| RR corner cases | **PASS** | Zero/zero, previous0, uint32 max, signed difference hai chiều, ratio vượt Q12.20; không clipping ngoài crest. |
| Read errors/abort/reset/repeated frames | **PASS** | Sai address, response-error, external abort với read pending, Window loss trong arithmetic/result, reset ở read/math/result, phục hồi. |
| VCD | **PASS** | Arithmetic806.857 byte; direct5.451.756 byte; stalled5.906.484 byte. |
| Phase3B/3A/2A regression | **PASS** | Năm Window suites, hai Sample suites, tám MLP suites; model/golden/previous RTL giữ nguyên. |
| Legacy Window / ADC | **FAIL** | Regression cũ tái hiện 511/512 và contiguous-valid3→1; expected baseline failures, không đổi thành PASS. |
| NumPy float32 bit identity | **FAIL** | Precision contract khác, đã đo trên cùng28 synthetic count frames; không phải lỗi mismatch RTL↔fixed oracle. |
| Verilator / Icarus | **NOT RUN** | Không có executable khả dụng; dùng Questa đã cài. |
| Hardware synthesis/timing/CDC/board | **NOT RUN** | Không có bằng chứng mapping/resource/timing mới. |
| Real preprocessing / feature-to-MLP parity | **NOT RUN** | Chưa có raw windows/quantization; chưa nối output96 vào MLP32. |

QuestaSim-64 2024.1, compiler/simulator2024.02 tại `C:/MentorGraphics/win64`. Python3.12.10 và NumPy2.5.4 từ venv Phase1A có sẵn; không cài phần mềm. Warning `vopt-10587` do `+acc` giữ trong log mỗi simulation; không suppress. Runner kiểm tra exit code, Fatal/Error/FAIL và required PASS marker. Marker hoàn tất command không thay cho assertions.

Mỗi engine suite có11.802 read requests và11.800 responses; hai requests bị reset/abort khi pending có chủ đích. Tổng hai suite: **76 accepted =60 successful +10 expected-fault completions +6 reset-aborts**. Các con số này là transaction kiểm thử, không phải dataset/classification accuracy. Scoreboard kiểm tra window payload, đủ347 responses, thứ tự địa chỉ, đủ12 words với `!==`, metadata, output stability và ownership; không force register DUT hoặc thay dữ liệu expected để PASS.

Thời gian từ edge start acceptance đến result_valid: **3.133 cycles** khi không stall =694 read cycles +3×293 cycles cho RMS roots +8×195 cycles cho các divisions còn lại. Mỗi read cần REQ/WAIT_RSP, không pipeline nhiều requests. Với seed stall hiện tại, các giao dịch hoàn tất được quan sát **3.332…3.396 cycles**. Không có maximum latency khi downstream có thể stall vô hạn. `done` chờ result handshake; release xảy ra sau đó. Clock TB20 ns không chứng minh FPGA đạt50 MHz; 62,66 µs chỉ là quy đổi giả định của3.133 cycles ở50 MHz.

Waveform: [features_direct.vcd](../build/phase3c/20261017_081043_552454/features_direct.vcd), [features_stalled.vcd](../build/phase3c/20261017_081043_552454/features_stalled.vcd), [arithmetic.vcd](../build/phase3c/20261017_081043_552454/arithmetic.vcd). Ghi ports, flattened12-feature payload và state/job; không cần dump toàn bộ vector memory. Coverage ở đây là directed/random functional assertions, không phải UCDB code coverage/formal proof.

## Lỗi đã sửa và lịch sử bằng chứng

Lượt [20261017_080946_344260](../build/phase3c/20261017_080946_344260): Python, lint/elaboration và arithmetic unit PASS; hai feature suites **FAIL** ở case signed16_min, `FAIL unexpected error 3`. Cast `$unsigned(sample*sample)` làm biểu thức multiply tự quyết định width16 trước khi assignment mở rộng, mất bình phương lớn; range guard phát hiện variance numerator sai. Đã sửa riêng RTL mới bằng magnitude17×17→34 bit. Giữ nguyên golden, toàn bộ assertions và log/VCD FAIL. Lượt sau tất cả28 cases và faults/reset PASS. Không làm yếu kiểm thử hoặc sửa module cũ.

Regression cũ chỉ chạy sau khi feature suites mới PASS, một lần qua runner Phase3B nguyên trạng: [Window results](../build/phase3b/20261017_081254_133949/results.json), [Sample results](../build/phase3a/20261017_081333_699309/results.json), [MLP results](../build/phase3a/20261017_081333_699309/mlp_results.json). MLP vẫn14/14 golden, class mask0xF,461 cycles; arithmetic180 cases, ROM164 địa chỉ/cổng, signed corners và bốn overflow suites PASS. Không chạy lại huấn luyện hoặc audit110.204 dòng CSV.

## Files và tái lập

Các file implementation/reference/test mới:

- [rtl/ecg/ecg_feature_math.sv](../rtl/ecg/ecg_feature_math.sv): iterative divider/sqrt có remainder.
- [rtl/ecg/ecg_feature_core.sv](../rtl/ecg/ecg_feature_core.sv): statistics,12 features, Window protocol và error/recovery.
- [tb/ecg/tb_ecg_feature_math.sv](../tb/ecg/tb_ecg_feature_math.sv), [tb/ecg/tb_ecg_feature_core.sv](../tb/ecg/tb_ecg_feature_core.sv): self-checking tests.
- [tools/ecg_feature_reference.py](../tools/ecg_feature_reference.py), [tests/test_ecg_feature_reference.py](../tests/test_ecg_feature_reference.py): independent oracles, vectors và Python tests.
- [tools/run_ecg_feature_tests.py](../tools/run_ecg_feature_tests.py): unique build/log/VCD/summary, source/vector hashes, optional prior regressions.
- `docs/phase3c_numeric_contract.md`, báo cáo này, `phase3c_precision.json`, `phase3c_results*.json`, `phase3c_integrity.json`: contract và bằng chứng. Các summary regression Phase3B/3A mới có timestamp riêng; không ghi đè report/summary cũ.

```powershell
# New feature tests only:
python -B tools/run_ecg_feature_tests.py
# Also run unchanged Window/Sample/MLP regression once after new tests PASS:
python -B tools/run_ecg_feature_tests.py --prior-regression
```

Runner dùng Questa đã cài, có thể chỉ định `--questa-dir PATH`. Reference generator dùng standard library; test NumPy tận dụng venv hiện có, nếu không có NumPy thì test tương ứng skip/NOT RUN trong log. Mỗi run tạo thư mục và summary mới; golden mới nằm trong build, không đè vector cũ.

[phase3c_integrity.json](phase3c_integrity.json) ghi hash snapshot137 file đầu phase, refs/remotes và source/vector/log/VCD evidence. Hai main refs vẫn giữ `7b9a4cc4...` (training) và `9e33a48d...` (RTL). Training working tree sạch; không commit/push/merge/reset/clean/delete. `git diff` tracked/staged không chứa thay đổi; các file phase trước và file mới vẫn chưa commit.

## Phần chưa thể chốt

Engine đã kiểm chứng đủ12 phép toán **trên miền count đã định nghĩa**. Để đưa vào pipeline ECG có model hiện tại còn cần raw ECG/annotation đại diện, mapping waveform→signed16, thứ tự filter/resample/quantize, sai số cho phép so với NumPy float32, cách chuyển feature96 sang miền model32 với range check, provenance metadata và budget hardware. Không thể chọn scale chỉ để feature vừa Q12.20 hoặc dùng synthetic-count agreement thay cho preprocessing parity.

Chưa nối Feature→MLP, không đổi normalization/weights, không thêm Master FSM/UART/APB/top. Các giới hạn checkpoint provenance và patient overlap từ Phase1A vẫn còn. Gate arithmetic/protocol của slice độc lập **PASS**; gate training-equivalent end-to-end vẫn **NOT RUN**.
