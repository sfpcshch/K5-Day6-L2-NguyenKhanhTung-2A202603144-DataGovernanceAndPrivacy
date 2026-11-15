"""Unit and integration tests for Track T09: Multi-Market Privacy Decision Gate."""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.common.context import RunContext
from src.common.review import AuditLog
from src.pipeline import load, process, rank, review, decide, run
from src.baselines.consent_baseline import run as run_baseline


FX_T09 = Path("fixtures/t09_privacy_gate")


def make_ctx(output_dir: Path, run_name: str = "poc") -> RunContext:
    output_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        track="t09",
        input_dir=FX_T09,
        output_dir=output_dir,
        config={"track": "t09", "owner": "Nguyen Khanh Tung (Data Protection & Governance Lead)", "budget": 12},
        seed=42,
        rng=np.random.default_rng(42),
        run_name=run_name,
        offline=True,
        audit=AuditLog(output_dir / "audit_log.jsonl"),
    )


@pytest.fixture
def t09_context(tmp_path: Path) -> RunContext:
    return make_ctx(tmp_path / "out")


def test_t09_pipeline_end_to_end(t09_context: RunContext):
    """Test full execution of T09 pipeline generating all deliverables."""
    run(t09_context)

    out = t09_context.output_dir
    assert (out / "decisions.csv").is_file()
    assert (out / "review_queue.csv").is_file()
    assert (out / "contact_sheet.html").is_file()
    assert (out / "decision.json").is_file()
    assert (out / "decision_log.csv").is_file()
    assert (out / "audit_log.jsonl").is_file()

    # Validate decisions.csv schema and completeness
    df_dec = pd.read_csv(out / "decisions.csv")
    assert list(df_dec.columns) == ["case_id", "decision", "reason_codes"]
    assert len(df_dec) == 12

    # Validate decision.json
    with open(out / "decision.json") as f:
        d_meta = json.load(f)
    assert d_meta["status"] in ("HOLD", "GO", "REWORK")
    assert d_meta["scope"] == "t09"
    assert "Nguyen Khanh Tung" in d_meta["owner"]


def test_t09_rule_engine_vietnam_law_91(t09_context: RunContext):
    """Test compliance checks against Vietnam Law 91/2025/QH15 and Decree 356/2025."""
    data = load(t09_context)
    scored = process(t09_context, data)

    # CASE-01: Legitimate interest not allowed in VN -> HOLD, NO_LAWFUL_BASIS
    c01 = scored[scored.case_id == "CASE-01"].iloc[0]
    assert c01.decision == "HOLD"
    assert "NO_LAWFUL_BASIS" in c01.reason_codes

    # CASE-03: Bundled consent without withdrawability and unbounded retention -> REWORK
    c03 = scored[scored.case_id == "CASE-03"].iloc[0]
    assert c03.decision == "REWORK"
    assert "CONSENT_INVALID" in c03.reason_codes
    assert "RETENTION_UNBOUNDED" in c03.reason_codes

    # CASE-07: Cross-border transfer without TIA dossier -> HOLD
    c07 = scored[scored.case_id == "CASE-07"].iloc[0]
    assert c07.decision == "HOLD"
    assert "XBORDER_NO_IMPACT_ASSESSMENT" in c07.reason_codes

    # CASE-12: Raw cloud retention without encryption and 10-year retention -> HOLD
    c12 = scored[scored.case_id == "CASE-12"].iloc[0]
    assert c12.decision == "HOLD"
    assert "NO_ENCRYPTION" in c12.reason_codes
    assert "RETENTION_EXCESSIVE" in c12.reason_codes


def test_t09_rule_engine_gdpr_and_international(t09_context: RunContext):
    """Test compliance checks against GDPR, CCPA, and PDPA."""
    data = load(t09_context)
    scored = process(t09_context, data)

    # CASE-02 (EU): Transfer to non-adequate third country without mechanism -> HOLD
    c02 = scored[scored.case_id == "CASE-02"].iloc[0]
    assert c02.decision == "HOLD"
    assert "XBORDER_NO_MECHANISM" in c02.reason_codes

    # CASE-04 (EU): In-cabin surveillance without DPIA -> HOLD
    c04 = scored[scored.case_id == "CASE-04"].iloc[0]
    assert c04.decision == "HOLD"
    assert "DPIA_MISSING" in c04.reason_codes

    # CASE-05 (US-CA): Notice at collection missing -> REWORK
    c05 = scored[scored.case_id == "CASE-05"].iloc[0]
    assert c05.decision == "REWORK"
    assert "NOTICE_MISSING" in c05.reason_codes

    # CASE-06 (SG): Valid LIA -> GO
    c06 = scored[scored.case_id == "CASE-06"].iloc[0]
    assert c06.decision == "GO"

    # CASE-08 (EU): Vendor ambiguity -> HOLD
    c08 = scored[scored.case_id == "CASE-08"].iloc[0]
    assert c08.decision == "HOLD"
    assert "AMBIGUOUS_NEEDS_LEGAL" in c08.reason_codes

    # CASE-10 (EU): Adequacy + DPIA + LIA -> GO
    c10 = scored[scored.case_id == "CASE-10"].iloc[0]
    assert c10.decision == "GO"


def test_t09_consent_baseline_critical_misses(tmp_path: Path):
    """Verify that naive consent baseline misclassifies risky cases as GO."""
    ctx_base = make_ctx(tmp_path / "baseline_out", run_name="baseline")
    run_baseline(ctx_base)
    df_base = pd.read_csv(ctx_base.output_dir / "decisions.csv")

    # Baseline falsely passes CASE-01, CASE-02, CASE-04, CASE-07, CASE-12
    c01 = df_base[df_base.case_id == "CASE-01"].iloc[0]
    assert c01.decision == "GO"

    c02 = df_base[df_base.case_id == "CASE-02"].iloc[0]
    assert c02.decision == "GO"

    c04 = df_base[df_base.case_id == "CASE-04"].iloc[0]
    assert c04.decision == "GO"


def test_t09_determinism(tmp_path: Path):
    """Verify pipeline output is 100% deterministic across multiple runs."""
    ctx1 = make_ctx(tmp_path / "out1")
    ctx2 = make_ctx(tmp_path / "out2")
    run(ctx1)
    run(ctx2)

    d1 = (tmp_path / "out1" / "decisions.csv").read_text()
    d2 = (tmp_path / "out2" / "decisions.csv").read_text()
    assert d1 == d2
