# Benchmark InfluxDB: tốc độ ghi, dung lượng, độ trễ truy vấn

Sinh bởi `benchmarks/benchmark.py` (dữ liệu thô: `reports/benchmark-results.json`). Chạy lại:
`uv run --env-file .env python benchmarks/benchmark.py --runs 5 --query-runs 50`

## Môi trường
| Mục | Giá trị |
| --- | --- |
| InfluxDB | v2.7.12 (Docker, image build từ `influxdb:2.7.12`) |
| Docker | không giới hạn CPU/RAM (`mem=0`, `nanocpus=0`); client Python cùng máy, localhost |
| Máy | AMD Ryzen 5 4600H, 12 luồng, 30 GB RAM, Linux |
| Tải nền | load average ≈ 0.67 trước, ≈ 1.1 sau; container idle ≈ 0.05% CPU, 285 MiB RAM |
| Container khi truy vấn | CPU snapshot 0.9% (original) / 2.4% (80k); RAM 261 / 365 MiB |

## 1. Tốc độ ghi và dung lượng
Mỗi lần chạy ghi vào **bucket tạm mới** (xoá sau đó), ghi đồng bộ (`SYNCHRONOUS`), chỉ đo thời gian gửi + server ack (không tính tạo line protocol). 5 lần/cấu hình.

| Dữ liệu | Số điểm | Batch | Median point/s | Min–Max point/s | Median dung lượng (B) | B/điểm |
| --- | --- | --- | --- | --- | --- | --- |
| CSV gốc (37,922 dòng, 37,920 hợp lệ) | 37,920 | 100 | 7,124 | 6,948–7,994 | 36,721,673 | 968 |
| | | 500 | 14,027 | 14,007–14,344 | 37,078,764 | 978 |
| | | 1000 | 16,529 | 16,294–16,632 | 37,454,044 | 988 |
| | | 5000 | 28,161 | 25,774–29,032 | 37,920,491 | 1000 |
| Mở rộng 80k (82,000 dòng, tổng hợp) | 82,000 | 100 | 6,900 | 6,883–6,978 | 41,346,708 | 504 |
| | | 500 | 14,001 | 13,901–14,109 | 42,112,677 | 514 |
| | | 1000 | 16,526 | 16,306–17,565 | 42,806,715 | 522 |
| | | 5000 | 27,129 | 26,408–27,716 | 43,990,168 | 537 |

Tham chiếu: line protocol 11,566,260 B (gốc), 25,198,992 B (80k); CSV 80k ≈ 82,001 dòng.

Nhận xét: tốc độ ghi tăng ~4 lần từ batch 100 lên 5000 rồi chững dần; batch 5000 đạt ~27–28k point/s.

> [!WARNING]
> Dung lượng đo bằng `du -sb` thư mục `engine/data/<id>` + `engine/wal/<id>` ngay sau khi ghi (chờ 2 s), chưa nén/compaction cuối cùng. Con số gần như **không tăng theo số điểm** (36.7 MB → 41.3 MB khi số điểm gấp 2,16 lần), nên phần lớn là chi phí cố định (WAL/index cấp phát trước), không phải kích thước TSM thực. Không dùng B/điểm làm tỉ lệ nén; để đo chính xác cần đợi snapshot/compaction (cache-snapshot-write-cold-duration mặc định 10 phút) hoặc dùng bộ dữ liệu lớn hơn.

## 2. Độ trễ truy vấn mean vs max
Cùng bucket, cùng khoảng thời gian (toàn bộ dữ liệu), trường `temperature`, `aggregateWindow(createEmpty: false)`. Đo phía client bằng `time.perf_counter()` quanh `query_api.query()` đã đọc hết kết quả; 5 lần khởi động bỏ đi, **50 lần đo**; p95 theo nội suy tuyến tính.

| Dữ liệu | Cửa sổ | Hàm | Số dòng kết quả | Median (ms) | p95 (ms) | Max (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| Gốc | 1h | mean | 2,163 | 27.5 | 46.6 | 52.1 |
| Gốc | 1h | max | 2,163 | 26.6 | 39.1 | 49.2 |
| Gốc | 1d | mean | 101 | 16.7 | 18.6 | 29.2 |
| Gốc | 1d | max | 101 | 16.7 | 17.9 | 25.3 |
| 80k | 1h | mean | 6,606 | 55.2 | 89.5 | 91.4 |
| 80k | 1h | max | 6,606 | 52.9 | 87.6 | 89.1 |
| 80k | 1d | mean | 286 | 24.3 | 25.3 | 45.4 |
| 80k | 1d | max | 286 | 24.1 | 25.4 | 40.0 |

**Kết luận so với mục tiêu 100 ms:** cả 8 cấu hình đều đạt (p95 cao nhất 89.5 ms, max 91.4 ms), nhưng mức dự trữ ở 80k/cửa sổ 1h chỉ còn ~10%. `mean` và `max` chênh nhau không đáng kể; độ trễ phụ thuộc chủ yếu vào số điểm và số dòng kết quả. Đây là kết quả trên máy đơn, localhost, truy vấn tuần tự, không có tải đồng thời.
