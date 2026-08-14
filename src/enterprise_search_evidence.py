"""Entitlement-aware enterprise-search claim evidence verification.

A search provider adapter supplies normalized ranked hits and ACL metadata. This
kernel proves which evidence was eligible for one actor, at one snapshot/time,
and whether it covers the declared claim units without relying on inaccessible
or stale documents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class EnterpriseSearchEvidenceRequest:
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget: float = 4.0
    not_after: float | None = None


@dataclass(frozen=True)
class EnterpriseSearchEvidenceReceipt:
    decision: Decision
    reasons: tuple[str, ...]
    digest: str
    metrics: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"decision": self.decision.value, "reasons": list(self.reasons), "digest": self.digest, "metrics": self.metrics, "result": self.result}


class EnterpriseSearchEvidence:
    MAX_HITS = 512
    MAX_UNITS = 128
    MAX_ENTITLEMENTS = 1024
    MAX_TEXT = 16_384
    MAX_INPUT_CHARS = 2_000_000
    BASE_WORK = 0.5
    HIT_WORK = 0.01
    VALID_PAYLOAD_KEYS = frozenset({"actor_id", "actor_entitlements", "query", "claim", "claim_units", "index_snapshot_digest", "hits", "policy", "expected_evidence_digest"})
    HIT_KEYS = frozenset({"document_id", "source_uri", "document_digest", "score", "indexed_at", "acl_any", "stance", "evidence_strength", "supports_units", "contradicts_units"})
    POLICY_KEYS = frozenset({"min_score", "min_evidence_strength", "max_age_seconds", "min_supporting_hits", "min_supporting_sources", "min_claim_coverage", "max_contradicted_units"})
    STANCES = frozenset({"support", "contradict", "neutral"})

    def __init__(self, *, now_fn: Callable[[], float] | None = None) -> None:
        self._now_fn = now_fn or time.time

    @classmethod
    def _text(cls, value: Any, label: str) -> str:
        if not isinstance(value, str): raise ValueError(f"{label}_type_invalid")
        value = value.strip()
        if not value: raise ValueError(f"{label}_missing")
        if len(value) > cls.MAX_TEXT: raise ValueError(f"{label}_too_long")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value): raise ValueError(f"{label}_control_character")
        return value

    @staticmethod
    def _unit(value: Any, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)): raise ValueError(f"{label}_invalid")
        value = float(value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0: raise ValueError(f"{label}_invalid")
        return value

    @staticmethod
    def _number(value: Any, label: str, *, minimum: float = 0.0) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)): raise ValueError(f"{label}_invalid")
        value = float(value)
        if not math.isfinite(value) or value < minimum: raise ValueError(f"{label}_invalid")
        return value

    @staticmethod
    def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum: raise ValueError(f"{label}_invalid")
        return value

    @staticmethod
    def _sha(value: Any, label: str) -> str:
        if not isinstance(value, str): raise ValueError(f"{label}_type_invalid")
        value = value.lower()
        if not _SHA256.fullmatch(value): raise ValueError(f"{label}_invalid")
        return value

    @classmethod
    def _text_list(cls, raw: Any, label: str, *, limit: int, allow_empty: bool = True) -> list[str]:
        if not isinstance(raw, list): raise ValueError(f"{label}_invalid")
        if len(raw) > limit: raise ValueError(f"{label}_over_limit")
        values = sorted({cls._text(value, f"{label}_{index}") for index, value in enumerate(raw)})
        if not allow_empty and not values: raise ValueError(f"{label}_empty")
        return values

    @classmethod
    def _policy(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping): raise ValueError("policy_missing")
        unknown = set(raw) - cls.POLICY_KEYS
        if unknown: raise ValueError("policy_keys_unknown:" + ",".join(sorted(unknown)))
        return {
            "min_score": cls._unit(raw.get("min_score", 0.6), "policy_min_score"),
            "min_evidence_strength": cls._unit(raw.get("min_evidence_strength", 0.5), "policy_min_evidence_strength"),
            "max_age_seconds": cls._number(raw.get("max_age_seconds", 86400.0), "policy_max_age_seconds"),
            "min_supporting_hits": cls._integer(raw.get("min_supporting_hits", 2), "policy_min_supporting_hits", minimum=1),
            "min_supporting_sources": cls._integer(raw.get("min_supporting_sources", 2), "policy_min_supporting_sources", minimum=1),
            "min_claim_coverage": cls._unit(raw.get("min_claim_coverage", 1.0), "policy_min_claim_coverage"),
            "max_contradicted_units": cls._integer(raw.get("max_contradicted_units", 0), "policy_max_contradicted_units"),
        }

    @classmethod
    def _hit(cls, raw: Any, index: int, *, now: float, actor_entitlements: set[str], claim_units: set[str], policy: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, Mapping): raise ValueError(f"hit_{index}_not_object")
        unknown = set(raw) - cls.HIT_KEYS
        if unknown: raise ValueError(f"hit_{index}_keys_unknown:" + ",".join(sorted(unknown)))
        stance = cls._text(raw.get("stance"), f"hit_{index}_stance").lower()
        if stance not in cls.STANCES: raise ValueError(f"hit_{index}_stance_invalid")
        score = cls._unit(raw.get("score"), f"hit_{index}_score")
        strength = cls._unit(raw.get("evidence_strength"), f"hit_{index}_evidence_strength")
        indexed_at = cls._number(raw.get("indexed_at"), f"hit_{index}_indexed_at")
        if indexed_at > now: raise ValueError(f"hit_{index}_indexed_in_future")
        acl_any = cls._text_list(raw.get("acl_any", []), f"hit_{index}_acl_any", limit=cls.MAX_ENTITLEMENTS)
        supports = cls._text_list(raw.get("supports_units", []), f"hit_{index}_supports_units", limit=cls.MAX_UNITS)
        contradicts = cls._text_list(raw.get("contradicts_units", []), f"hit_{index}_contradicts_units", limit=cls.MAX_UNITS)
        unknown_units = (set(supports) | set(contradicts)) - claim_units
        if unknown_units: raise ValueError(f"hit_{index}_unknown_claim_units:" + ",".join(sorted(unknown_units)))
        entitled = not acl_any or bool(set(acl_any) & actor_entitlements)
        age_seconds = now - indexed_at
        fresh = age_seconds <= policy["max_age_seconds"]
        score_ok = score >= policy["min_score"]
        strength_ok = strength >= policy["min_evidence_strength"]
        eligible = entitled and fresh and score_ok and strength_ok
        return {"document_id": cls._text(raw.get("document_id"), f"hit_{index}_document_id"), "source_uri": cls._text(raw.get("source_uri"), f"hit_{index}_source_uri"), "document_digest": cls._sha(raw.get("document_digest"), f"hit_{index}_document_digest"), "score": score, "indexed_at": indexed_at, "age_seconds": age_seconds, "acl_any": acl_any, "entitled": entitled, "fresh": fresh, "score_ok": score_ok, "strength_ok": strength_ok, "eligible": eligible, "stance": stance, "evidence_strength": strength, "weighted_evidence": score * strength, "supports_units": supports, "contradicts_units": contradicts}

    @classmethod
    def _request_size(cls, req: EnterpriseSearchEvidenceRequest) -> int:
        try:
            raw = json.dumps(
                {"subject_id": req.subject_id, "payload": req.payload, "budget": req.budget, "not_after": req.not_after},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("request_not_json_serializable") from exc
        if len(raw) > cls.MAX_INPUT_CHARS:
            raise ValueError("input_too_large")
        return len(raw)

    def evaluate(self, req: EnterpriseSearchEvidenceRequest) -> EnterpriseSearchEvidenceReceipt:
        reasons: list[str] = []
        request_shape_blocked = False
        try:
            self._request_size(req)
        except ValueError as exc:
            reasons.append(str(exc)); request_shape_blocked = True
        try: subject_id = self._text(req.subject_id, "subject_id")
        except ValueError as exc: subject_id = ""; reasons.append(str(exc))
        try: budget = self._number(req.budget, "budget", minimum=0.001)
        except ValueError as exc: budget = 0.0; reasons.append(str(exc))
        if not isinstance(req.payload, Mapping): payload: Mapping[str, Any] = {}; reasons.append("payload_not_object"); request_shape_blocked = True
        else:
            payload = req.payload
            unknown = set(payload) - self.VALID_PAYLOAD_KEYS
            if unknown: reasons.append("payload_keys_unknown:" + ",".join(sorted(unknown)))
        result: dict[str, Any] = {}; work_units = self.BASE_WORK
        if not request_shape_blocked:
            try:
                now = self._number(self._now_fn(), "evaluator_now")
                if req.not_after is not None and now > self._number(req.not_after, "not_after"): reasons.append("request_expired")
                actor_id = self._text(payload.get("actor_id"), "actor_id")
                actor_entitlements_list = self._text_list(payload.get("actor_entitlements", []), "actor_entitlements", limit=self.MAX_ENTITLEMENTS)
                actor_entitlements = set(actor_entitlements_list)
                query = self._text(payload.get("query"), "query"); claim = self._text(payload.get("claim"), "claim")
                claim_units_list = self._text_list(payload.get("claim_units"), "claim_units", limit=self.MAX_UNITS, allow_empty=False); claim_units = set(claim_units_list)
                snapshot = self._sha(payload.get("index_snapshot_digest"), "index_snapshot_digest"); policy = self._policy(payload.get("policy"))
                hits_raw = payload.get("hits")
                if not isinstance(hits_raw, list): raise ValueError("hits_missing")
                if len(hits_raw) > self.MAX_HITS: raise ValueError("hits_over_limit")
                work_units += len(hits_raw) * self.HIT_WORK
                if work_units > budget: reasons.append("work_budget_exceeded")
                else:
                    hits = [self._hit(raw, index, now=now, actor_entitlements=actor_entitlements, claim_units=claim_units, policy=policy) for index, raw in enumerate(hits_raw)]
                    if len({hit["document_id"] for hit in hits}) != len(hits): raise ValueError("duplicate_document_id")
                    hits.sort(key=lambda hit: (-hit["score"], hit["document_id"]))
                    eligible = [hit for hit in hits if hit["eligible"]]; supports = [hit for hit in eligible if hit["stance"] == "support"]
                    supported_units = {unit for hit in supports for unit in hit["supports_units"] if hit["weighted_evidence"] > 0.0}
                    contradicted_units = {unit for hit in eligible for unit in hit["contradicts_units"] if hit["weighted_evidence"] > 0.0}
                    support_sources = {hit["source_uri"] for hit in supports}; coverage = len(supported_units) / len(claim_units)
                    if len(supports) < policy["min_supporting_hits"]: reasons.append("insufficient_supporting_hits")
                    if len(support_sources) < policy["min_supporting_sources"]: reasons.append("insufficient_supporting_sources")
                    if coverage < policy["min_claim_coverage"]: reasons.append("insufficient_claim_coverage")
                    if len(contradicted_units) > policy["max_contradicted_units"]: reasons.append("contradicted_claim_units_exceeded")
                    manifest = {"schema": "glaciereq.enterprise-search-evidence.v1", "actor_id": actor_id, "actor_entitlements_digest": _digest(actor_entitlements_list), "query": query, "claim": claim, "claim_units": claim_units_list, "index_snapshot_digest": snapshot, "policy": policy, "ranked_hits": hits}
                    evidence_digest = _digest(manifest); expected = payload.get("expected_evidence_digest")
                    if expected is not None and self._sha(expected, "expected_evidence_digest") != evidence_digest: reasons.append("expected_evidence_digest_mismatch")
                    result = {"evidence_digest": evidence_digest, "eligible_hit_count": len(eligible), "supporting_hit_count": len(supports), "supporting_source_count": len(support_sources), "supported_units": sorted(supported_units), "contradicted_units": sorted(contradicted_units), "claim_coverage": coverage, "inaccessible_hit_count": sum(not hit["entitled"] for hit in hits), "stale_hit_count": sum(not hit["fresh"] for hit in hits), "weak_evidence_hit_count": sum(not hit["strength_ok"] for hit in hits)}
            except ValueError as exc: reasons.append(str(exc))
        decision = Decision.REFUSE if reasons else Decision.ALLOW
        if not reasons: reasons = ["claim_supported_by_entitled_fresh_enterprise_evidence"]
        metrics = {"work_units": work_units, "budget_units": budget, "eligible_hit_count": result.get("eligible_hit_count", 0), "supporting_hit_count": result.get("supporting_hit_count", 0), "supporting_source_count": result.get("supporting_source_count", 0), "claim_coverage": result.get("claim_coverage", 0.0), "inaccessible_hit_count": result.get("inaccessible_hit_count", 0), "stale_hit_count": result.get("stale_hit_count", 0), "weak_evidence_hit_count": result.get("weak_evidence_hit_count", 0)}
        digest = _digest({"subject_id": subject_id, "decision": decision.value, "reasons": reasons, "result": result, "metrics": metrics})
        return EnterpriseSearchEvidenceReceipt(decision, tuple(reasons), digest, metrics, result)


def _read_input(path: str | None) -> str:
    limit = EnterpriseSearchEvidence.MAX_INPUT_CHARS
    if path:
        source = Path(path)
        if source.stat().st_size > limit * 4: raise ValueError("input_too_large")
        raw = source.read_text(encoding="utf-8")
    else: raw = sys.stdin.read(limit + 1)
    if len(raw) > limit: raise ValueError("input_too_large")
    return raw


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify enterprise search claim evidence with ACL and freshness checks.")
    parser.add_argument("--input", "-i", help="request JSON file; defaults to stdin"); args = parser.parse_args(argv)
    try:
        data = json.loads(_read_input(args.input))
        if not isinstance(data, Mapping): raise ValueError("request JSON must be an object")
        payload = data.get("payload", {})
        if not isinstance(payload, Mapping): raise ValueError("payload must be an object")
        receipt = EnterpriseSearchEvidence().evaluate(EnterpriseSearchEvidenceRequest(subject_id=data.get("subject_id", ""), payload=dict(payload), budget=data.get("budget", 4.0), not_after=data.get("not_after")))
    except Exception as exc:
        print(json.dumps({"decision": "ERROR", "reasons": [f"cli_input_error:{type(exc).__name__}:{exc}"]}, sort_keys=True)); return 2
    print(json.dumps(receipt.as_dict(), indent=2, sort_keys=True))
    return 0 if receipt.decision is Decision.ALLOW else 1
