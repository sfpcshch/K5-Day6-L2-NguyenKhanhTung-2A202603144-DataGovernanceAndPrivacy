# Ablation Study — Multi-Market Privacy Decision Gate (Track T09)

> Đánh giá so sánh vai trò của từng thành phần luật định và chứng minh lỗ hổng của các baseline.

| Model / Variant | Crit-Miss Rate (Eval) | False HOLD (Eval) | Guardrail PASS? | Accuracy (Eval) | Crit-Miss (All 12) | Accuracy (All 12) |
| --- | --- | --- | --- | --- | --- | --- |
| Full PoC (Privacy Gate) | 0.0000 | 0.0000 | PASS | 1.0000 | 0.0000 | 1.0000 |
| All-HOLD (Trivial Baseline) | 0.0000 | 1.0000 | FAIL | 0.7500 | 0.0000 | 0.6667 |
| Consent-only Baseline | 0.6667 | 0.0000 | PASS | 0.5000 | 0.7000 | 0.3333 |
| Ablation: No Cross-Border Check | 0.0000 | 0.0000 | PASS | 1.0000 | 0.2000 | 0.8333 |
| Ablation: No DPIA Check | 0.0000 | 0.0000 | PASS | 1.0000 | 0.1000 | 0.9167 |

### Phân tích kết quả bóc tách (Ablation Findings):
1. **Full PoC**: Đạt Critical-miss Rate = 0.0000 trên cả eval và all cases, vượt qua guardrail (`False HOLD = 0.0000 <= 0.50`).
2. **All-HOLD Trivial Baseline**: Đạt Critical-miss Rate = 0.0000, nhưng **FAIL GUARDRAIL** (`False HOLD = 1.0000 > 0.50`), chứng minh rằng một cổng chặn cực đoan sẽ làm tê liệt toàn bộ luồng dữ liệu hợp pháp.
3. **Consent-only Baseline**: Thất bại nặng nề với Critical-miss Rate = 0.6667 trên eval và 0.5000 trên toàn bộ tập dữ liệu do bỏ qua các yêu cầu phi-consent.
4. **Bỏ kiểm tra Cross-border**: Làm tăng tỷ lệ lọt vi phạm do không chặn được việc chuyển dữ liệu sang nước thứ ba không có cơ chế bảo vệ (như CASE-02 sang non-adequate country hoặc CASE-07 sang Singapore chưa có TIA).
5. **Bỏ kiểm tra DPIA**: Làm lọt các hoạt động giám sát cabin rủi ro cao (CASE-04) vi phạm trực tiếp Điều 35 GDPR.