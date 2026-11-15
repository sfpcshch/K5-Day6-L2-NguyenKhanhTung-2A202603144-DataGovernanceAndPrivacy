"""Consent-only baseline for T09: Multi-Market Privacy Decision Gate.

Official baseline specification from docs/tracks/T09.md:
"Baseline: Sai có chủ ý: 'có consent thì GO' — dùng để chứng minh checklist
này không đủ (so false GO với GT)."
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from ..common.contact_sheet import render_contact_sheet
from ..common.context import RunContext
from ..common.decision import Decision, write_decision
from ..common.manifest import verify_manifest
from ..common.review import make_review_queue, write_review_queue
from ..metrics.tracks import get_track


def load(ctx: RunContext) -> dict:
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="baseline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems)")

    cases_dir = ctx.input_dir / "cases"
    case_files = sorted(cases_dir.glob("CASE-*.json"))
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in case_files]
    return {"manifest": pd.read_csv(manifest) if manifest.exists() else None, "cases": cases}


def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    rows = []
    for c in data["cases"]:
        cid = c["case_id"]
        consent = c.get("consent", {})
        has_consent = bool(consent.get("obtained", False))
        has_lawful_basis = c.get("lawful_basis") not in ("unknown", "n/a", None, "")

        # Naive rule: if consent was obtained or lawful_basis is declared, mark GO
        if has_consent or has_lawful_basis:
            decision = "GO"
            reason_codes = ""
            score = 0.0
            reason = "Consent obtained or lawful basis declared"
        else:
            decision = "HOLD"
            reason_codes = "NO_LAWFUL_BASIS"
            score = 1.0
            reason = "No consent or declared lawful basis"

        rows.append({
            "case_id": cid,
            "decision": decision,
            "reason_codes": reason_codes,
            "score": score,
            "reason": reason,
            "market": c.get("market", "unknown"),
        })

    return pd.DataFrame(rows)


def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    budget = int(ctx.param("budget", 12))
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
    return q


def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    return scored


def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    return Decision(
        status="HOLD",
        reason_code="BASELINE_ONLY",
        reason="Consent-only baseline: fails to detect cross-border and DPIA gaps",
        owner=ctx.config.get("owner", "baseline"),
        scope=ctx.track,
        evidence=[str(ctx.out("decisions.csv"))],
    )


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)

    cols = [c for c in ["case_id", "decision", "reason_codes"] if c in final.columns]
    final[cols].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
