# Phase 1A — ECG Model Package & Golden Reference

Ngày audit: 2026-10-16. Training reference chỉ đọc: `AI_FSM_ECG@7b9a4cc4f3d7ddb1c6e47b51ab8d8a979b69fe1d`. Integration: `ECG@983f803b3e3d815a411c46da7ae66006a9d5af03`. Báo cáo này bổ sung kết quả mới; các báo cáo Phase 0 được giữ nguyên như bằng chứng tại thời điểm đó.

## Kết quả chính

| Kiểm tra | Kết quả | Bằng chứng / giới hạn |
|---|---|---|
| Feature dataset đủ schema, dữ liệu hữu hạn, bốn nhãn | PASS | 110.204 dòng, 48 patient ID; kiểm tra toàn bộ CSV |
| Thứ tự 12 feature, shape checkpoint 12→8→4 | PASS | AST source, metadata checkpoint, CSV, golden vector đều thống nhất |
| Scaler tái tạo từ train split của CSV | PASS | 12 mean và 12 scale khớp chính xác; sai số lớn nhất 0 |
| Tái tạo 164 word `weight.hex`, kiểm tra `weight.mi` | PASS | Thứ tự mean/inverse-scale/W1/b1/W2/b2; output-neuron-major |
| Q4.12 không làm mất miền giá trị | FAIL | Reciprocal `f_zc` bị clamp; năm feature có giá trị ngoài miền trên CSV thật |
| Q12.20 so với float trên toàn bộ CSV | PASS | 110.204/110.204 dự đoán giống nhau; 0 overflow; đạt ngân sách sai số từng tầng |
| Golden vector từ feature dataset đủ bốn nhãn | PASS | 4 dòng thật có số dòng CSV, patient ID, source label; thêm 10 probe tổng hợp |
| Python regression và NumPy/SciPy/PyTorch parity | PASS | 37/37 tests PASS; 0 FAIL; 0 NOT RUN |
| Patient-disjoint train/validation/test | FAIL | Cả 48 patient ID xuất hiện trong cả ba tập được tái tạo |
| Lịch sử huấn luyện/lưu checkpoint | FAIL | Source không gọi `torch.save`; không có run manifest hoặc bằng chứng checkpoint thuộc lần fit scaler này |
| Preprocessing từ ECG raw, annotation semantics | NOT RUN | Chỉ có feature CSV; chưa có raw ECG/annotation gốc |
| RTL/hardware parity của Q12.20 | NOT RUN | Không sửa RTL; đây là hợp đồng số học thử nghiệm cho Stage A |

Kết quả từng Python test và phiên bản thư viện nằm trong [phase1a_tests.json](phase1a_tests.json), log thực tế trong [phase1a_tests.log](phase1a_tests.log). Kết quả toàn bộ dataset nằm trong [phase1a_dataset_results.json](phase1a_dataset_results.json); các kiểm tra package/500 vector trong [phase1a_results.json](phase1a_results.json). Chỉ báo runtime `NOT RUN` trong `phase1a_results.json` có phạm vi lệnh audit package dùng thư viện chuẩn; kiểm thử runtime được chạy riêng và ghi trong `phase1a_tests.json`.

Kiểm tra bất biến **PASS**: 70 file đã có từ đầu Phase 1A giữ nguyên SHA-256, bao gồm training, RTL và các báo cáo Phase 0. Hai ref `main` giữ nguyên; training working tree sạch. [phase1a_integrity.json](phase1a_integrity.json) lưu trạng thái Git và kết quả đối chiếu; không fetch/push/merge/commit.

## Dataset và provenance

Input trong workspace: `datasets/AI_Training_12_Features_250Hz_V2.csv`, tức `../datasets/AI_Training_12_Features_250Hz_V2.csv` từ repository RTL hoặc `../../datasets/AI_Training_12_Features_250Hz_V2.csv` từ thư mục `docs/` này. Không sao chép dataset vào repository RTL.

- Kích thước: 27.641.016 byte.
- SHA-256: `a82cf74a931d9e00a09617be156416ec269e2ff986dc681dacacf7509cde38b4`.
- Feature CSV do người dùng bổ sung; nguồn raw, đơn vị biên độ, gain/offset, filter trước CSV, phiên bản dataset đầu vào và annotation chưa được cung cấp. Các trường đó vẫn **NOT RUN**, không được suy ra từ tên file.

| Quần thể | Normal 0 | Fast 1 | Slow 2 | Abnormal 3 | Tổng |
|---|---:|---:|---:|---:|---:|
| Feature dataset đầy đủ | 52.422 | 9.353 | 9.353 | 39.076 | 110.204 |
| `label.txt` đi với 500 vector cũ | 490 | 0 | 0 | 10 | 500 |

Hai quần thể được audit riêng. `feature_extract_column.py` đọc các cột Excel theo vị trí và ghi decimal; không có chuỗi chuyển đổi chứng minh nguồn gốc/encoding của `first_500.txt`. Vì vậy, phần so sánh 500 vector chỉ dùng **giả thuyết** giải mã 12 raw feature signed Q4.12. Không dùng 500 vector để suy ra phân bố đầy đủ hoặc công bố accuracy.

Tái tạo split đúng source: stratified row-level 70/15/15 với `random_state=42` ở cả hai lần chia. Train có 77.142 dòng; validation/test mỗi tập 16.531. `StandardScaler.fit(X_train)` cho đúng từng mean/scale trong file gốc. Đây là bằng chứng dataset/scaler phù hợp, chưa chứng minh checkpoint có cùng lịch sử huấn luyện. Không đổi split, nhãn hay huấn luyện lại trong Phase 1A.

Patient overlap là lỗi đã đo được ở split tái tạo: train∩validation, train∩test và validation∩test đều có 48 ID. Checkpoint không kèm split membership lưu từ lần huấn luyện, nên accuracy độc lập theo patient và provenance của tập test thật vẫn **NOT RUN**.

## Hợp đồng feature và model

Thứ tự được xác nhận:

```text
0 f_rms          1 f_var          2 f_peak       3 f_zc
4 f_ptp          5 f_crest        6 f_half_ratio 7 f_max
8 f_rr           9 f_rr_prev     10 f_rr_ratio  11 f_rr_diff
```

`create_dataset.py` khai báo/return đúng thứ tự này; `train_2.py` chọn mọi cột `f_` theo thứ tự CSV; CSV được bổ sung khớp. Checkpoint chỉ có `fc1.weight[8,12]`, `fc1.bias[8]`, `fc2.weight[4,8]`, `fc2.bias[4]`, float32 little-endian. Không softmax khi lấy argmax; hòa logits chọn ID nhỏ nhất.

```text
z = (features - means) / scales
pre = W1 z + b1
h = max(pre, 0)
y = W2 h + b2
class = argmax(y)
```

ROM 164 địa chỉ: mean `0..11`, reciprocal-scale `12..23`, W1 `24..119`, b1 `120..127`, W2 `128..159`, b2 `160..163`. Hàng là output neuron, cột là input. [model_manifest.json](model_manifest.json) lưu SHA-256 cho training artifacts, generator và golden artifacts; không thay `weight.hex` gốc.

Reference float dùng binary64 và `math.fsum`, độc lập với source training và RTL. Checkpoint đọc bằng bộ giải mã metadata có whitelist, chỉ cho phép OrderedDict/float32 tensor descriptors, không import hay chạy training script. Reference fixed dùng số nguyên với kiểm tra width từng bước. Fraction oracle độc lập kiểm tra bit-exact trên 500 vector và golden cases; test toy MLP có kết quả tính tay, gồm số âm, ReLU, bias và argmax.

Reference feature float giữ công thức trong Phase 0: variance population; sign(-/0/+) cho ZC và chia N; RMS thực; crest clip 0..15; nửa cửa sổ 173/174; RR tính giây với epsilon `1e-9`. DFT độc lập thực hiện đúng cấu trúc Fourier 500→347 trên dữ liệu tổng hợp, kiểm tra bằng SciPy. Điều này không xác minh rằng feature CSV đã được sinh từ raw theo đúng quy trình. Không triển khai fixed-point feature extraction/sqrt/division; Stage A bắt đầu tại vector 12 feature.

## Q4.12: lỗi đã xác nhận

Exporter gốc: `int(value*4096)`, cắt về zero rồi clamp signed16; miền `[-8, 7.999755859375]`.

- Địa chỉ 15, `1/scale[f_zc] = 57.77128774964532`; integer chưa clamp 236631; lưu `0x7FFF = 7.999755859375`. Đây là lỗi mất gain chuẩn hóa, không phải chỉ sai số vài LSB.
- Các tham số khác không clamp. 164 word khớp exporter chỉ chứng minh serialization, không chứng minh package đúng số học.

| Feature | Max trong toàn dataset | Số giá trị bị clamp nếu xuất raw feature theo Q4.12 |
|---|---:|---:|
| `f_var` | 15,82455826 | 2 |
| `f_ptp` | 10,01904011 | 3 |
| `f_crest` | 9,27745914 | 128 |
| `f_half_ratio` | 13,66970062 | 1 |
| `f_rr_ratio` | 47,99999712 | 87 |

Các số đếm là theo phần tử feature, không cộng thành số dòng duy nhất. Các feature còn lại không vượt miền Q4.12 trong CSV này. Mean/scaler quantization và raw-feature quantization được phân biệt.

Khi thay tham số bằng ROM Q4.12 rồi vẫn tính binary64 với raw feature chưa lượng tử hóa, 4.823/110.204 mẫu đổi class so với checkpoint float. Không quy toàn bộ sai lệch riêng cho một parameter: phép đo gồm mọi tham số lượng tử hóa và clipping. Đây không phải mô phỏng datapath/FSM của RTL cũ.

## Định dạng đề xuất: signed32, 20 bit phần lẻ

Tên Q12.20 trong báo cáo **tính sign trong 12 bit nguyên**. Word32 two's complement; miền `[-2048, 2047.9999990463257]`; LSB `2^-20`. Dùng chung cho raw feature, mean, reciprocal-scale, weight, bias, normalized, pre-activation, hidden và logits.

| Bước | Width / binary point | Quy tắc |
|---|---|---|
| Encode | signed32, F=20 | Round-to-nearest ties-to-even; từ chối overflow, không clamp |
| `x - mean` | signed33, F=20 | Sign-extend trước trừ |
| Nhân reciprocal | signed65, F=40 | Nhân đầy đủ; RNE khi chia `2^20`, kiểm tra signed32 |
| MAC | signed64 product, F=40 | Tích signed32×signed32 |
| Cộng dồn + bias | signed68, F=40 | Bias `<<20`; cộng đủ 12 hoặc 8 tích rồi mới RNE |
| Layer output/ReLU | signed32, F=20 | Kiểm tra overflow trước ReLU; so sánh signed |
| Argmax | 4 signed logits | Không softmax; tie chọn index nhỏ nhất |

64 bit đủ cho mỗi MAC product; 68 bit chứa tổng 12 tích signed32 cực trị và bias đã căn binary point. Normalizer dùng 65 bit vì phép trừ có thể cần 33 bit. Mọi bước narrowing đều được kiểm tra; Python integer không được dùng để âm thầm bỏ qua width hardware.

File thử nghiệm [model_q12_20.hex](../tests/vectors/model_q12_20.hex) có 164 word 8-hex-digit, cùng địa chỉ, không tương thích word16 của RTL hiện tại. Đây là artifact reference để review, không phải model đã được phê duyệt triển khai. Chi phí DSP/BRAM, chu kỳ MAC, ROM latency, interface width và xử lý overflow ở RTL chưa được chọn/đo.

CSV quan sát được normalized max-abs 98,495; pre-activation 363,584; hidden 159,537; logits 699,893. Q12.20 đủ miền cho toàn bộ mẫu hiện có. Không có chứng minh cho input ngoài dataset: half-ratio có mẫu số gần zero có thể rất lớn; min logit margin đo được chỉ `7.5216e-6`. Không bảo đảm mọi input tương lai giữ class; cần hợp đồng miền đầu vào và chính sách overflow rõ ràng.

## So sánh số học toàn bộ 110.204 mẫu

Ngân sách sai số regression được khai báo trong script: normalized `0,001`; pre-activation/hidden `0,002`; logits `0,01`; yêu cầu không đổi class và không overflow. Đây là tiêu chí kỹ thuật Phase 1A, không phải ngưỡng chấp nhận lâm sàng hay quyết định cuối cùng cho RTL.

| Đại lượng | Max abs error Q12.20 so với float | Max abs error tham số Q4.12 so với float |
|---|---:|---:|
| Normalized | 0,0000460148 | 13,691976 |
| Pre-activation | 0,0000790844 | 16,986320 |
| Hidden ReLU | 0,0000633277 | 16,986320 |
| Logits | 0,0003580533 | 14,310801 |
| Số mẫu đổi class | **0** | **4.823** |

Q12.20: **PASS**, 0 overflow; sai số encode input/parameter tối đa `2^-21 = 4.76837158203125e-7`. Parameter-only Q4.12: **FAIL** theo cùng ngân sách.

Tỉ lệ dự đoán trùng nhãn trên **toàn bộ pool CSV** là 88,7318% cho float và Q12.20, 87,5404% cho tham số Q4.12. Đây chỉ là thống kê mô tả trên dữ liệu có thể chứa training rows. Không gọi đó là accuracy held-out/clinical; phép kiểm chứng đó **NOT RUN**. Confusion matrices và các dòng đổi class có trong JSON.

500 vector cũ, dưới giả thuyết decode đã nêu: Q12.20 khớp float 500/500; parameter-only Q4.12 đổi một class tại index 257 (zero-based). Không trộn kết quả này với số đo CSV đầy đủ.

## Golden package và tái lập

[ecg_golden.json](../tests/vectors/ecg_golden.json) gồm 14 cases:

- 4 dòng thật, chọn dòng xuất hiện đầu tiên của từng source label 0–3 theo thứ tự CSV, có số dòng 1-based tính cả header và patient ID.
- 4 waveform tổng hợp có 500 sample gốc, 347 sample sau DFT, RR/symbol và đủ bốn **rule label**. Không phải dữ liệu bệnh nhân.
- 4 probe feature phi sinh lý với seed `20261016` để phủ cả bốn **class do model dự đoán**.
- Mean-vector và crest=15 để kiểm tra normalizer-zero/miền vượt Q4.12.

Mỗi case có raw feature, normalized, pre-activation, hidden, logits, class; fixed trace có encoded input, normalizer product và accumulator hai tầng. Source label, rule label và model prediction là trường riêng: model không bắt buộc dự đoán đúng nhãn nguồn. Ví dụ dòng thật đầu tiên nhãn 3 được model dự đoán 0; vector vẫn giữ nguyên, không chọn lại để làm đẹp accuracy. Vector thật chỉ có feature, không bịa raw waveform/annotation.

Chạy từ repository RTL:

```powershell
# Không cần third-party packages cho package audit và toàn bộ fixed/float sweep.
python -B tools/audit_ecg_model.py --output-root .
python -B tools/audit_ecg_model.py --check --output-root .
python -B tools/audit_ecg_dataset.py

# Môi trường riêng đã tạo ở workspace, để chạy đối chiếu runtime.
& ../.phase1a_env/Scripts/python.exe -B tools/audit_ecg_dataset.py --scaler-only
& ../.phase1a_env/Scripts/python.exe -B tools/run_ecg_tests.py
```

Dataset mặc định là `../datasets/AI_Training_12_Features_250Hz_V2.csv` từ repository RTL; có thể truyền `--dataset PATH`. `--scaler-only` giữ kết quả sweep đã lưu khi hash dataset/reference khớp, tránh chạy lại toàn bộ. Audit model trả **exit 1** vì các lỗi baseline đã xác nhận; bốn kiểm tra `--check` về byte-for-byte reproducibility đều **PASS**, exit 1 không có nghĩa generation thất bại. Full numeric audit trả exit 0 cho phần số học; `patient_disjoint` là một diagnostic riêng **FAIL**, không bị đổi thành PASS bởi exit 0 này.

Để dựng môi trường mới, cài thư viện trong venv riêng, không chạy training script:

```powershell
python -m venv ../.phase1a_env
& ../.phase1a_env/Scripts/python.exe -m pip install --index-url https://pypi.org/simple numpy scipy pandas scikit-learn
& ../.phase1a_env/Scripts/python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch
```

Phiên bản thực tế: Python 3.12.10, NumPy 2.5.4, SciPy 1.18.1, pandas 3.0.6, scikit-learn 1.9.1, PyTorch 2.14.1+cpu; được ghi trong test JSON/scaler JSON. Lần cài ban đầu **FAIL** do quyền temp của sandbox; `ensurepip` sau escalation **PASS**. Lần tải mặc định **FAIL** do `getaddrinfo failed`; dùng PyPI chính thức đã **PASS**. Môi trường `.phase1a_env` nằm ngoài hai repository; không cài vào Python hệ thống. Reproducibility byte-exact đã kiểm tra trên CPython 3.12.10/Windows của audit này; DFT binary64 có thể khác vài bit cuối giữa math library của các nền tảng.

## Gate và bước nhỏ tiếp theo

Phần kiểm chứng số học/feature-vector package đã có bằng chứng **PASS** cho dữ liệu hiện có. Gate phê duyệt model tổng thể vẫn **FAIL** do clipping trong package gốc, patient overlap và thiếu checkpoint save provenance; raw preprocessing/hardware validation là **NOT RUN**.

Đề xuất bước nhỏ nhất: review hợp đồng Q12.20, rồi Stage A ROM/scaler/MLP độc lập trong repository RTL. Replay 14 golden cases, yêu cầu bit-exact ở normalized, accumulator, ReLU, logits và class; kiểm tra signed MAC, RNE, overflow, reset và handshake. Chưa ghép window/feature/APB/UART trong slice này. Khôi phục lineage checkpoint và sửa split/đóng gói model là công việc training riêng cần quyết định rõ; không thay training source trong Phase 1A.

Các quyết định còn mở: miền input được hỗ trợ; action của hardware khi overflow; format tối ưu DSP so với uniform32; chính sách annotation/RR; provenance checkpoint; raw ECG/annotation và preprocessing upstream; ngưỡng chấp nhận accuracy theo patient. Không có commit, push, merge hay sửa RTL/main trong phase này.
