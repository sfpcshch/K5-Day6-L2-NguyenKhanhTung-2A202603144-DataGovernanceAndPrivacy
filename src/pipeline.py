"""Field-to-Release PoC Pipeline for T09: Multi-Market Privacy Decision Gate.

Data Governance & Privacy Pipeline (AI20K Day 06):
    01 load      Verify manifest SHA-256 and ingest cross-border cases + policy rules
    02 process   Multi-market policy evaluation (GDPR, VN Luật 91/2025, CCPA/CPRA, SG, IN)
    03 rank      Prioritise review queue by compliance risk + HTML compliance sheet
    04 review    Human-in-the-loop: legal sign-off, override handling, and JSONL audit trail
    05 decide    Dataset release decision: GO / HOLD / REWORK with reason_code & owner
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd
import yaml

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, canonical_status, write_decision
from .common.manifest import verify_manifest
from .common.review import apply_overrides, load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    """Load inputs and verify cryptographic provenance."""
    if ctx.track != "t09":
        raise NotImplementedError(
            f"Track '{ctx.track}' is not implemented by this group. "
            f"Group G02 implemented T09 (Multi-Market Privacy Decision Gate)."
        )

    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")

    cases_dir = ctx.input_dir / "cases"
    if not cases_dir.exists():
        raise FileNotFoundError(f"Missing cases directory in {ctx.input_dir}")

    case_files = sorted(cases_dir.glob("CASE-*.json"))
    cases = []
    for p in case_files:
        cases.append(json.loads(p.read_text(encoding="utf-8")))

    # Load policy rules
    rule_file = ctx.param("policy_file", "rules/policy_rules.yaml")
    rule_path = ctx.input_dir / rule_file
    if not rule_path.exists():
        rule_path = ctx.input_dir / "rules/policy_example.yaml"
    rules = yaml.safe_load(rule_path.read_text(encoding="utf-8")) if rule_path.exists() else {}

    return {
        "manifest": pd.read_csv(manifest) if manifest.exists() else None,
        "cases": cases,
        "rules": rules,
    }


# ---------------------------------------------------------------- Policy Engine
def _evaluate_case(case: dict[str, Any]) -> tuple[str, list[str], str]:
    """Evaluate privacy compliance rules across EU, VN, US-CA, SG, and IN jurisdictions.

    Returns:
        (decision, reason_codes, human_rationale)
        Precedence: HOLD > REWORK > GO.
    """
    market = case.get("market", "")
    reasons: list[str] = []
    actions: list[str] = []
    notes: list[str] = []

    lawful_basis = case.get("lawful_basis", "")
    consent = case.get("consent", {})
    transfer = case.get("transfer", {})
    storage = case.get("storage", {})
    retention_days = case.get("retention_days")
    dpia_done = bool(case.get("dpia_done", False))
    ambiguity = str(case.get("ambiguity_notes", "")).strip()
    data_types = case.get("data_types", [])

    # 1. Jurisdiction: VIETNAM (Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 & NĐ 356/2025/NĐ-CP)
    if market == "VN":
        # VN has NO legitimate interest exception (Đ.9, Đ.19)
        valid_vn_bases = {"consent", "contract", "legal_obligation", "vital_interest", "public_task"}
        if lawful_basis not in valid_vn_bases:
            reasons.append("NO_LAWFUL_BASIS")
            actions.append("HOLD")
            notes.append("VN Luật 91/2025 Đ.9 & Đ.19: Không có căn cứ 'lợi ích hợp pháp'; cần sự đồng ý hoặc miễn trừ luật định")

        # Consent validity: must be voluntary, specific, withdrawable (Đ.9, Đ.10)
        if lawful_basis == "consent":
            if not consent.get("granular", False) or not consent.get("withdrawable", False):
                reasons.append("CONSENT_INVALID")
                actions.append("REWORK")
                notes.append("VN Luật 91/2025 Đ.9 & Đ.10: Sự đồng ý gộp/không thể rút lại là vô hiệu; cần xin lại đồng ý cụ thể")

        # Cross-border transfer: requires TIA dossier filed with authority within 60 days (Đ.21, NĐ 356)
        if transfer.get("cross_border", False) and not transfer.get("transfer_impact_assessment", False):
            reasons.append("XBORDER_NO_IMPACT_ASSESSMENT")
            actions.append("HOLD")
            notes.append("VN Luật 91/2025 Đ.21: Chuyển dữ liệu ra nước ngoài chưa lập/nộp hồ sơ đánh giá tác động TIA")

        # DPIA requirement (Đ.20)
        if not dpia_done:
            reasons.append("DPIA_MISSING")
            actions.append("HOLD")
            notes.append("VN Luật 91/2025 Đ.20: Thiếu hồ sơ đánh giá tác động xử lý dữ liệu cá nhân")

    # 2. Jurisdiction: EUROPEAN UNION (GDPR - Regulation (EU) 2016/679)
    elif market == "EU":
        # Cross-border transfer: requires adequacy decision or transfer mechanism (Chapter V)
        if transfer.get("cross_border", False):
            mechanism = transfer.get("mechanism")
            destination = str(transfer.get("destination", ""))
            if mechanism in (None, "unknown", "none", "null", "") or "non-adequate" in destination:
                if mechanism not in ("adequacy", "scc", "bcr"):
                    reasons.append("XBORDER_NO_MECHANISM")
                    actions.append("HOLD")
                    notes.append("GDPR Chapter V (Art. 44-49): Chuyển dữ liệu sang nước thứ ba thiếu cơ chế bảo đảm (SCC/BCR/Adequacy)")

        # DPIA requirement for high-risk monitoring (Art. 35)
        if ("in_cabin_video" in data_types or "face" in data_types) and not dpia_done:
            reasons.append("DPIA_MISSING")
            actions.append("HOLD")
            notes.append("GDPR Art. 35 & EDPB 01/2020: Giám sát cabin/khuôn mặt có rủi ro cao bắt buộc phải có DPIA")

        # Controller / Processor ambiguity (Art. 26, 28)
        if ambiguity and ("processor" in ambiguity.lower() or "controller" in ambiguity.lower()):
            reasons.append("AMBIGUOUS_NEEDS_LEGAL")
            actions.append("HOLD")
            notes.append("GDPR Art. 26/28: Bất định hợp đồng về vai trò bên kiểm soát/xử lý cần pháp chế làm rõ")

    # 3. Jurisdiction: UNITED STATES - CALIFORNIA (CCPA / CPRA)
    elif market == "US-CA":
        # Notice at collection required before/at point of collection (§ 1798.100(b))
        if not case.get("notice_given", True):
            reasons.append("NOTICE_MISSING")
            actions.append("REWORK")
            notes.append("CCPA § 1798.100(b): Thiếu thông báo thu thập dữ liệu (Notice at Collection) trước khi thu thập")

        # Sensitive Personal Information (precise location) + Business threshold doubt (§ 1798.121)
        if "precise_location" in data_types and ambiguity:
            reasons.append("AMBIGUOUS_NEEDS_LEGAL")
            actions.append("HOLD")
            notes.append("CCPA § 1798.121: Thu thập vị trí chính xác (SPI) kèm bất định ngưỡng doanh nghiệp thuộc phạm vi áp dụng")

    # 4. Jurisdiction: INDIA (DPDP Act 2023 / Rules 2025)
    elif market == "IN":
        # Consent verification record missing
        if consent.get("obtained", False) and not consent.get("record_available", True):
            reasons.append("CONSENT_RECORD_MISSING")
            actions.append("HOLD")
            notes.append("DPDP Act 2023 Sec. 6: Thiếu hồ sơ chứng minh sự đồng ý có thể kiểm toán; chuẩn bị tuân thủ 13/05/2027")

    # 5. Jurisdiction: SINGAPORE (PDPA 2012)
    elif market == "SG":
        # Check Legitimate Interests exception compliance (Section 15A)
        if lawful_basis == "legitimate_interest" and not case.get("li_assessment_done", False):
            reasons.append("NO_LAWFUL_BASIS")
            actions.append("HOLD")
            notes.append("SG PDPA Sec. 15A: Thiếu đánh giá lợi ích hợp pháp (LIA) bắt buộc")

    # -------------------------------------------------------------------------
    # Universal Data Governance & Security Rules
    # -------------------------------------------------------------------------
    # Encryption at rest
    if storage.get("raw_retained", False) and not storage.get("encryption_at_rest", True):
        reasons.append("NO_ENCRYPTION")
        actions.append("HOLD")
        notes.append("Bảo mật dữ liệu: Dữ liệu thô lưu trữ trên đám mây không mã hóa là vi phạm an ninh thông tin")

    # Retention limits
    if retention_days is None:
        reasons.append("RETENTION_UNBOUNDED")
        actions.append("REWORK")
        notes.append("Giới hạn lưu trữ: Thời hạn lưu trữ không xác định; cần ấn định thời hạn xóa dữ liệu cụ thể")
    elif retention_days > 730:  # > 2 years without special basis
        reasons.append("RETENTION_EXCESSIVE")
        actions.append("HOLD")
        notes.append(f"Giới hạn lưu trữ: Thời gian lưu trữ {retention_days} ngày (>2 năm) là quá mức cần thiết")

    # Final Precedence: HOLD > REWORK > GO
    if "HOLD" in actions:
        final_decision = "HOLD"
    elif "REWORK" in actions:
        final_decision = "REWORK"
    else:
        final_decision = "GO"
        notes.append("Tất cả tiêu chí pháp lý và quản trị dữ liệu đã được thỏa mãn đầy đủ")

    return final_decision, reasons, " | ".join(notes)


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    """Execute Privacy Policy Engine across all cases."""
    if ctx.track != "t09":
        raise NotImplementedError(
            f"Track '{ctx.track}' is not implemented by this group. "
            f"Group G02 implemented T09 (Multi-Market Privacy Decision Gate)."
        )

    cases = data["cases"]
    results = []

    for c in cases:
        cid = c["case_id"]
        decision, reasons, rationale = _evaluate_case(c)

        # Suspicion score: HOLD=1.0, REWORK=0.7, GO=0.0
        if decision == "HOLD":
            score = 1.0
        elif decision == "REWORK":
            score = 0.70
        else:
            score = 0.0

        # Semicolon-separated reason codes for metric contract
        reason_codes_str = ";".join(reasons)

        results.append({
            "case_id": cid,
            "decision": decision,
            "reason_codes": reason_codes_str,
            "score": score,
            "reason": rationale,
            "market": c.get("market", "unknown"),
            "lawful_basis": c.get("lawful_basis", ""),
            "purpose": c.get("purpose", ""),
            "transfer_cross_border": bool(c.get("transfer", {}).get("cross_border", False)),
            "dpia_done": bool(c.get("dpia_done", False)),
            "retention_days": c.get("retention_days"),
        })

    return pd.DataFrame(results)


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Rank cases by risk severity for human review."""
    budget = int(ctx.param("budget", len(scored)))
    q = make_review_queue(
        scored,
        id_col="case_id",
        score_col="score",
        budget=budget,
        reason_col="reason",
        action_col="decision",
        slice_col="market",
    )
    write_review_queue(q, ctx.out("review_queue.csv"))

    # Render offline compliance review sheet
    render_contact_sheet(
        q,
        ctx.out("contact_sheet.html"),
        image_root=ctx.input_dir,
        title=f"T09 Privacy Decision Gate Review Queue (N={len(q)})",
    )
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Human-in-the-loop: apply legal officer sign-off and overrides with audit log."""
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if reviewed_path.exists():
        reviewed = load_review_decisions(reviewed_path)
        ctx.stats["n_reviewed"] = len(reviewed)

        overridden = apply_overrides(scored, reviewed, id_col="case_id", value_col="decision", audit=ctx.audit)

        for r in reviewed.itertuples(index=False):
            if r.reviewer_decision in {"approve", "escalate", "skip"}:
                ctx.audit.log(
                    actor=r.reviewer,
                    action=f"review:{r.reviewer_decision}",
                    item_id=r.item_id,
                    before=None,
                    after=r.reviewer_decision,
                    reason=r.review_note,
                )
        return overridden

    ctx.audit.log(actor="pipeline", action="review_queue_generated", item_id="review_queue.csv", after=f"budget={len(queue)}")
    return scored


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    """System-level Decision Gate: Release GO / HOLD / REWORK."""
    hold_count = int((final["decision"] == "HOLD").sum())
    rework_count = int((final["decision"] == "REWORK").sum())
    go_count = int((final["decision"] == "GO").sum())
    total_count = len(final)

    owner = ctx.config.get("owner", "Nguyen Khanh Tung (Data Protection & Governance Lead)")
    evidence = [str(ctx.out("decisions.csv")), str(ctx.out("review_queue.csv"))]

    if hold_count > 0:
        return Decision(
            status="HOLD",
            reason_code="PRIVACY_RISKS_DETECTED",
            reason=f"Privacy Gate: {hold_count}/{total_count} cases blocked on HOLD, {rework_count} require REWORK before release",
            owner=owner,
            scope=ctx.track,
            evidence=evidence,
            metrics={"total_cases": total_count, "hold_count": hold_count, "rework_count": rework_count, "go_count": go_count},
        )
    if rework_count > 0:
        return Decision(
            status="REWORK",
            reason_code="REWORK_REQUIRED",
            reason=f"Privacy Gate: {rework_count}/{total_count} cases require contractual or notice adjustments",
            owner=owner,
            scope=ctx.track,
            evidence=evidence,
            metrics={"total_cases": total_count, "hold_count": 0, "rework_count": rework_count, "go_count": go_count},
        )

    return Decision(
        status="GO",
        reason_code="PRIVACY_GATE_PASSED",
        reason=f"Privacy Gate: all {total_count} cases passed privacy compliance validation",
        owner=owner,
        scope=ctx.track,
        evidence=evidence,
        metrics={"total_cases": total_count, "hold_count": 0, "rework_count": 0, "go_count": go_count},
    )


def run(ctx: RunContext) -> None:
    """Execute complete 5-step contract for T09."""
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)

    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)

    # Output decisions.csv with required columns: case_id, decision, reason_codes
    cols = [c for c in ["case_id", "decision", "reason_codes"] if c in final.columns]
    final[cols].to_csv(ctx.out(spec.pred_file), index=False)

    decision = decide(ctx, final)
    write_decision(decision, ctx.out("decision.json"), ctx.out("decision_log.csv"))
