"""STEP 11-10 — Deterministic Consensus 계산 (synthesis 무관)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stock_platform.ai.candidate_assessment.scoring import clamp_score
from stock_platform.ai.candidate_consensus.constants import (
    DETERMINISTIC_VERSION,
    FORBIDDEN_RESULT_KEYS,
    MAX_CONF_CRITICAL_CONFLICT,
    MAX_CONF_FAMILY_1,
    MAX_CONF_MAJOR_DISAGREE,
    MAX_CONF_MOCK_ONLY,
    MAX_CONF_NO_REVIEW_MAJORITY,
    MAX_CONF_UNSCORED,
    SCORE_MAX,
    SCORE_MIN,
)


def strip_forbidden_fields(
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """금지 필드 제거."""

    if not payload:
        return {}, []
    violations: list[str] = []

    def _walk(obj: Any, path: str = "") -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for key, value in obj.items():
                full = f"{path}.{key}" if path else str(key)
                if str(key).lower() in FORBIDDEN_RESULT_KEYS:
                    violations.append(full)
                    continue
                out[key] = _walk(value, full)
            return out
        if isinstance(obj, list):
            return [_walk(item, path) for item in obj]
        return obj

    cleaned = _walk(payload)
    if not isinstance(cleaned, dict):
        cleaned = {}
    return cleaned, violations


def _agreement_level(spread: float, member_count: int) -> str:
    if member_count < 2:
        return "INSUFFICIENT"
    if spread < 10:
        return "STRONG_AGREEMENT"
    if spread < 20:
        return "MODERATE_AGREEMENT"
    if spread < 35:
        return "WEAK_AGREEMENT"
    return "SPLIT"


def _disagreement_level(analytical_spread: float, risk_spread: float) -> str:
    combined = max(analytical_spread, risk_spread * 0.8)
    if combined < 5:
        return "NONE"
    if combined < 15:
        return "LOW"
    if combined < 25:
        return "MEDIUM"
    if combined < 40:
        return "HIGH"
    return "CRITICAL"


def _apply_confidence_caps(
    raw: float,
    *,
    members: list[dict[str, Any]],
    agreement_level: str,
    disagreement_level: str,
    conflicts: list[dict[str, Any]],
    warnings: list[str],
) -> float:
    conf = max(0.0, min(1.0, float(raw)))
    cap = 1.0

    reviewed = sum(
        1
        for m in members
        if m.get("review_decision") in {"APPROVED", "APPROVED_WITH_WARNINGS"}
    )
    if reviewed < max(1, len(members) // 2 + 1):
        cap = min(cap, MAX_CONF_NO_REVIEW_MAJORITY)

    families = {m.get("provider_family") for m in members}
    if len(families) == 1 and len(members) > 1:
        cap = min(cap, MAX_CONF_FAMILY_1)

    if any("UNSCORED" in w for w in warnings):
        cap = min(cap, MAX_CONF_UNSCORED)

    if agreement_level in {"SPLIT", "WEAK_AGREEMENT"}:
        cap = min(cap, MAX_CONF_MAJOR_DISAGREE)

    if disagreement_level == "CRITICAL" or any(
        c.get("severity") == "CRITICAL" for c in conflicts
    ):
        cap = min(cap, MAX_CONF_CRITICAL_CONFLICT)

    providers = {(m.get("provider_code") or "").lower() for m in members}
    if providers <= {"mock", ""}:
        cap = min(cap, MAX_CONF_MOCK_ONLY)

    return round(min(conf, cap), 4)


class AIConsensusCalculationService:
    """가중치 기반 deterministic consensus — external AI 호출 없음."""

    def calculate(
        self, included_members_with_weights: list[dict[str, Any]]
    ) -> dict[str, Any]:
        members = [
            m
            for m in included_members_with_weights
            if m.get("included", True) and float(m.get("normalized_weight") or 0) > 0
        ]
        warnings: list[str] = []

        if len(members) < 2:
            return {
                "ok": False,
                "code": "INSUFFICIENT_MEMBERS",
                "warnings": ["INSUFFICIENT_MEMBERS"],
                "external_ai_called": False,
            }

        analytical_values = [
            clamp_score(m.get("analytical_score")) for m in members
        ]
        risk_values = [clamp_score(m.get("risk_score")) for m in members]
        confidence_values = [
            max(0.0, min(1.0, float(m.get("confidence") or 0.5)))
            for m in members
        ]

        weights = [float(m.get("normalized_weight") or 0) for m in members]
        weight_sum = sum(weights) or 1.0

        analytical = sum(a * w for a, w in zip(analytical_values, weights)) / weight_sum
        risk = sum(r * w for r, w in zip(risk_values, weights)) / weight_sum
        confidence_raw = (
            sum(c * w for c, w in zip(confidence_values, weights)) / weight_sum
        )

        analytical_spread = max(analytical_values) - min(analytical_values)
        risk_spread = max(risk_values) - min(risk_values)
        agreement = _agreement_level(analytical_spread, len(members))
        disagreement = _disagreement_level(analytical_spread, risk_spread)

        factors, factor_warnings = self._build_factors(members, weights)
        warnings.extend(factor_warnings)

        conflicts, conflict_warnings = self._build_conflicts(
            members,
            analytical_spread=analytical_spread,
            risk_spread=risk_spread,
            disagreement=disagreement,
        )
        warnings.extend(conflict_warnings)

        minority_risks = self._minority_critical_risks(members, weights)

        confidence = _apply_confidence_caps(
            confidence_raw,
            members=members,
            agreement_level=agreement,
            disagreement_level=disagreement,
            conflicts=conflicts,
            warnings=warnings,
        )

        deterministic = {
            "deterministic_version": DETERMINISTIC_VERSION,
            "analytical_score": round(clamp_score(analytical), 2),
            "risk_score": round(clamp_score(risk), 2),
            "overall_score": round(clamp_score(analytical), 2),
            "confidence": confidence,
            "agreement_level": agreement,
            "disagreement_level": disagreement,
            "analytical_spread": round(analytical_spread, 2),
            "risk_spread": round(risk_spread, 2),
            "member_count": len(members),
            "minority_critical_risks": minority_risks,
        }

        safe_result = {
            "deterministic": deterministic,
            "factors_summary": factors[:30],
            "conflicts_summary": conflicts[:20],
        }
        cleaned, violations = strip_forbidden_fields(safe_result)
        warnings.extend([f"FORBIDDEN:{v}" for v in violations])

        result_hash = hashlib.sha256(
            json.dumps(cleaned, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:64]

        new_status = "VALIDATED_WITH_WARNINGS" if warnings else "VALIDATED"

        return {
            "ok": True,
            "analytical_score": deterministic["analytical_score"],
            "risk_score": deterministic["risk_score"],
            "overall_score": deterministic["overall_score"],
            "confidence": confidence,
            "agreement_level": agreement,
            "disagreement_level": disagreement,
            "factors": factors,
            "conflicts": conflicts,
            "safe_result": cleaned,
            "warnings": warnings,
            "result_hash": result_hash,
            "consensus_status": new_status,
            "external_ai_called": False,
        }

    def _build_factors(
        self,
        members: list[dict[str, Any]],
        weights: list[float],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        bucket: dict[str, dict[str, Any]] = {}

        for member, weight in zip(members, weights):
            aid = member.get("assessment_id")
            body = member.get("result_body") or {}
            for factor_type, direction_default in (
                ("POSITIVE", "POSITIVE"),
                ("NEGATIVE", "NEGATIVE"),
                ("NEUTRAL", "NEUTRAL"),
            ):
                key_name = {
                    "POSITIVE": "positive_factors",
                    "NEGATIVE": "negative_factors",
                    "NEUTRAL": "neutral_factors",
                }[factor_type]
                for factor in list(body.get(key_name) or [])[:15]:
                    if isinstance(factor, dict):
                        code = str(
                            factor.get("code") or factor.get("name") or "FACTOR"
                        )[:80]
                        summary = str(
                            factor.get("summary") or factor.get("description") or ""
                        )[:1000]
                        direction = str(
                            factor.get("direction") or direction_default
                        ).upper()
                    else:
                        code = str(factor)[:80]
                        summary = str(factor)[:1000]
                        direction = direction_default

                    bucket_key = f"{factor_type}:{code}"
                    if bucket_key not in bucket:
                        bucket[bucket_key] = {
                            "factor_type": factor_type,
                            "factor_code": code,
                            "direction": direction,
                            "support_count": 0,
                            "oppose_count": 0,
                            "neutral_count": 0,
                            "weighted_support": 0.0,
                            "evidence_summary": summary,
                            "member_assessment_ids": [],
                        }
                    entry = bucket[bucket_key]
                    if direction in {"POSITIVE", "NEGATIVE"}:
                        if factor_type == "POSITIVE":
                            entry["support_count"] += 1
                            entry["weighted_support"] += weight
                        elif factor_type == "NEGATIVE":
                            entry["oppose_count"] += 1
                    else:
                        entry["neutral_count"] += 1
                    if aid not in entry["member_assessment_ids"]:
                        entry["member_assessment_ids"].append(aid)

        factors: list[dict[str, Any]] = []
        for entry in bucket.values():
            total = (
                entry["support_count"] + entry["oppose_count"] + entry["neutral_count"]
            )
            if total == 0:
                continue
            ratio = entry["weighted_support"] / max(total, 1)
            if ratio >= 0.75:
                strength = "STRONG"
            elif ratio >= 0.5:
                strength = "MODERATE"
            elif ratio >= 0.25:
                strength = "WEAK"
            else:
                strength = "SPLIT"
            entry["consensus_strength"] = strength
            factors.append(entry)

        if not factors:
            warnings.append("NO_STRUCTURED_FACTORS")
        return factors, warnings

    def _build_conflicts(
        self,
        members: list[dict[str, Any]],
        *,
        analytical_spread: float,
        risk_spread: float,
        disagreement: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        conflicts: list[dict[str, Any]] = []

        if analytical_spread >= 35:
            conflicts.append(
                {
                    "conflict_code": "ANALYTICAL_SCORE_SPLIT",
                    "conflict_type": "SCORE",
                    "severity": "HIGH" if analytical_spread < 50 else "CRITICAL",
                    "description": f"analytical spread {analytical_spread:.1f}",
                    "member_assessment_ids": [
                        m.get("assessment_id") for m in members
                    ],
                    "resolution_status": "UNRESOLVED",
                }
            )

        if risk_spread >= 30:
            conflicts.append(
                {
                    "conflict_code": "RISK_SCORE_SPLIT",
                    "conflict_type": "RISK",
                    "severity": "MEDIUM" if risk_spread < 45 else "HIGH",
                    "description": f"risk spread {risk_spread:.1f}",
                    "member_assessment_ids": [
                        m.get("assessment_id") for m in members
                    ],
                    "resolution_status": "UNRESOLVED",
                }
            )

        family_map: dict[str, list[int]] = {}
        for m in members:
            fam = m.get("provider_family") or "unknown"
            family_map.setdefault(fam, []).append(m.get("assessment_id"))

        for fam, ids in family_map.items():
            if len(ids) > 1 and fam != "mock":
                conflicts.append(
                    {
                        "conflict_code": "SAME_PROVIDER_FAMILY",
                        "conflict_type": "INDEPENDENCE",
                        "severity": "LOW",
                        "description": f"provider family {fam} duplicated",
                        "member_assessment_ids": ids,
                        "resolution_status": "ACKNOWLEDGED",
                    }
                )

        if disagreement == "CRITICAL":
            warnings.append("CRITICAL_DISAGREEMENT")

        return conflicts, warnings

    @staticmethod
    def _minority_critical_risks(
        members: list[dict[str, Any]],
        weights: list[float],
    ) -> list[dict[str, Any]]:
        """소수 멤버의 CRITICAL/HIGH risk factor 보존."""

        preserved: list[dict[str, Any]] = []
        for member, weight in zip(members, weights):
            if weight >= 0.25:
                continue
            body = member.get("result_body") or {}
            for risk in list(body.get("risk_factors") or [])[:10]:
                if not isinstance(risk, dict):
                    continue
                severity = str(risk.get("severity") or "").upper()
                if severity not in {"CRITICAL", "HIGH"}:
                    continue
                preserved.append(
                    {
                        "assessment_id": member.get("assessment_id"),
                        "risk_type": risk.get("type") or risk.get("code"),
                        "severity": severity,
                        "summary": str(
                            risk.get("summary") or risk.get("description") or ""
                        )[:500],
                        "weight": weight,
                    }
                )
        return preserved[:20]
