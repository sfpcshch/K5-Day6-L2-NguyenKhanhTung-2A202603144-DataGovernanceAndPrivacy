"""Debate and Adversarial Test Suite for Track T09: Multi-Market Privacy Decision Gate.

Fulfills Bonus criteria: 'debate tìm bug thật bằng test'.
Tests adversarial exploits, regulatory evasion attempts, dark patterns, and edge cases:
1. The 'All-HOLD' trivial baseline exploit (demonstrates guardrail failure)
2. 'Consent Bundling' dark pattern evasion
3. 'Cross-border Laundering' to non-adequate third countries
4. 'Retention Evasion' (unbounded and excessive retention periods)
5. 'Vietnam Legitimate Interest Illusion' (attempting to circumvent VN Law 91/2025)
6. 'Future Law Timing Misattribution' (handling upcoming vs present enforceable regulations)
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from src.pipeline import _evaluate_case
from src.metrics.tracks import get_track


FX_T09 = Path("fixtures/t09_privacy_gate")


def test_adversarial_all_hold_fails_guardrail():
    """Debate 1: Can a trivial 'reject everything' model game the Critical-miss Rate?

    Finding: While All-HOLD achieves 0.000 Critical-miss Rate, it catastrophically
    violates the constrained guardrail: False HOLD rate = 1.000 > 0.50 (FAIL).
    """
    gt_path = Path("reports/internal_gt_t09.csv")
    spec = get_track("t09")

    # Construct trivial All-HOLD predictions
    cases_dir = FX_T09 / "cases"
    case_ids = [f"CASE-{i:02d}" for i in range(1, 13)]
    pred_df = pd.DataFrame([{"case_id": cid, "decision": "HOLD", "reason_codes": "TRIVIAL"} for cid in case_ids])

    tmp_p = FX_T09 / "all_hold_tmp.csv"
    pred_df.to_csv(tmp_p, index=False)
    try:
        res = spec.evaluator(gt_path, tmp_p, {"split": "eval", "max_false_hold": 0.5})
        m_dict = {m.name: m.value for m in res.metrics}

        assert m_dict["Critical-miss Rate"] == 0.0
        assert m_dict["False HOLD rate"] == 1.0
        # Guardrail MUST fail
        assert m_dict["Guardrail: False HOLD rate <= 0.5"] == 0.0  # 0 = FAIL
    finally:
        if tmp_p.exists():
            tmp_p.unlink()


def test_adversarial_consent_bundling_dark_pattern():
    """Debate 2: Developer bundles ADAS consent into general Terms of Service without granularity.

    Under Vietnam Law 91/2025/QH15 Art. 9 & 10 and GDPR Art. 7, bundled or non-withdrawable
    consent is void. The gate must catch this and return REWORK, not GO.
    """
    adversarial_case = {
        "case_id": "ADV-01-BUNDLED-CONSENT",
        "market": "VN",
        "purpose": "ADAS model training",
        "data_types": ["exterior_video"],
        "lawful_basis": "consent",
        "consent": {
            "obtained": True,
            "granular": False,         # Bundled with general terms
            "withdrawable": False,     # Cannot withdraw without closing account
            "record_available": True,
        },
        "storage": {"raw_retained": False, "location": "on_device", "encryption_at_rest": True},
        "transfer": {"cross_border": False, "destination": None, "mechanism": None, "transfer_impact_assessment": False},
        "retention_days": 90,
        "dpia_done": True,
        "ambiguity_notes": "",
    }

    decision, reason_codes, reason = _evaluate_case(adversarial_case)
    assert decision == "REWORK"
    assert "CONSENT_INVALID" in reason_codes
    assert "đồng ý gộp" in reason


def test_adversarial_cross_border_data_laundering():
    """Debate 3: Developer claims 'adequacy' to a country that does not have an adequacy decision.

    A naive rule engine that only checks `mechanism is not None` would be fooled.
    The gate must verify valid mechanisms or valid TIA dossiers.
    """
    adversarial_case = {
        "case_id": "ADV-02-XBORDER-LAUNDERING",
        "market": "EU",
        "purpose": "ADAS model training",
        "data_types": ["exterior_video"],
        "lawful_basis": "consent",
        "consent": {"obtained": True, "granular": True, "withdrawable": True, "record_available": True},
        "storage": {"raw_retained": False, "location": "on_device", "encryption_at_rest": True},
        "transfer": {
            "cross_border": True,
            "destination": "unregulated tax haven",
            "mechanism": "None",       # No valid transfer safeguard
            "transfer_impact_assessment": False,
        },
        "retention_days": 90,
        "dpia_done": True,
        "ambiguity_notes": "",
    }

    decision, reason_codes, reason = _evaluate_case(adversarial_case)
    assert decision == "HOLD"
    assert "XBORDER_NO_MECHANISM" in reason_codes


def test_adversarial_retention_evasion():
    """Debate 4: Developer sets indefinite or extreme retention periods (e.g. 20 years).

    Under GDPR Art. 5(1)(e) (Storage Limitation) and Vietnam Law 91/2025 Art. 19,
    raw unencrypted video retained indefinitely must be blocked.
    """
    # Case A: Indefinite retention
    case_indefinite = {
        "case_id": "ADV-03A-INDEFINITE",
        "market": "VN",
        "purpose": "ADAS model training",
        "data_types": ["exterior_video"],
        "lawful_basis": "consent",
        "consent": {"obtained": True, "granular": True, "withdrawable": True, "record_available": True},
        "storage": {"raw_retained": True, "location": "cloud", "encryption_at_rest": True},
        "transfer": {"cross_border": False, "destination": None, "mechanism": None, "transfer_impact_assessment": False},
        "retention_days": None,        # Indefinite
        "dpia_done": True,
        "ambiguity_notes": "",
    }
    dec_a, codes_a, _ = _evaluate_case(case_indefinite)
    assert dec_a == "REWORK"
    assert "RETENTION_UNBOUNDED" in codes_a

    # Case B: 20-year unencrypted cloud retention
    case_excessive = {
        "case_id": "ADV-03B-EXCESSIVE",
        "market": "VN",
        "purpose": "ADAS model training",
        "data_types": ["exterior_video"],
        "lawful_basis": "consent",
        "consent": {"obtained": True, "granular": True, "withdrawable": True, "record_available": True},
        "storage": {"raw_retained": True, "location": "cloud", "encryption_at_rest": False},
        "transfer": {"cross_border": False, "destination": None, "mechanism": None, "transfer_impact_assessment": False},
        "retention_days": 7300,        # 20 years
        "dpia_done": True,
        "ambiguity_notes": "",
    }
    dec_b, codes_b, _ = _evaluate_case(case_excessive)
    assert dec_b == "HOLD"
    assert "NO_ENCRYPTION" in codes_b
    assert "RETENTION_EXCESSIVE" in codes_b


def test_adversarial_vietnam_legitimate_interest_attempt():
    """Debate 5: Developer imports EU GDPR Art. 6(1)(f) legitimate interest into Vietnam.

    In Vietnam, commercial ADAS data collection has no legitimate interest basis.
    The gate must strictly reject this justification with NO_LAWFUL_BASIS.
    """
    adversarial_case = {
        "case_id": "ADV-04-VN-LI-ATTEMPT",
        "market": "VN",
        "purpose": "ADAS model training",
        "data_types": ["exterior_video"],
        "lawful_basis": "legitimate_interest",  # Invalid in VN
        "consent": {"obtained": False, "granular": False, "withdrawable": False, "record_available": False},
        "storage": {"raw_retained": False, "location": "on_device", "encryption_at_rest": True},
        "transfer": {"cross_border": False, "destination": None, "mechanism": None, "transfer_impact_assessment": False},
        "retention_days": 90,
        "dpia_done": True,
        "ambiguity_notes": "",
    }
    decision, reason_codes, _ = _evaluate_case(adversarial_case)
    assert decision == "HOLD"
    assert "NO_LAWFUL_BASIS" in reason_codes
