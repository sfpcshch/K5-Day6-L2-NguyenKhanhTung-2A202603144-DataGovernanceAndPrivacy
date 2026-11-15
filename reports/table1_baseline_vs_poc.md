Baseline: `baseline` (git 83573cd, seed 42) · PoC: `poc` (git 83573cd, seed 42)

| Metric (unit) | Slice | Baseline | PoC | Δ abs | Δ rel | Better | N |
|---|---|---|---|---|---|---|---|
| **Critical-miss Rate** (risky cases given GO / risky cases) | all | 0.6667 | 0.0000 | -0.6667 | -100.0% | lower | 4 |
| High-risk HOLD Recall (risky cases not GO / risky cases) | all | 0.3333 | 1.0000 | 0.6667 | +200.0% | higher | None |
| False HOLD rate (GO cases blocked / GO cases) | all | 0.0000 | 0.0000 | 0.0000 | baseline=0 | lower | None |
| Exact decision accuracy (fraction) | all | 0.5000 | 1.0000 | 0.5000 | +100.0% | higher | 4 |
| Guardrail: False HOLD rate <= 0.5 (1 = pass, 0 = fail (constrained primary)) | all | 1.0000 | 1.0000 | 0.0000 | +0.0% | higher | None |
| Reason-code match (risky) (risky cases with ≥1 correct reason code) | all | 0.0000 | 1.0000 | 1.0000 | baseline=0 | higher | None |
| Runtime / 100 items (s) | all | 0.1525 | 0.2833 | | | lower | |
