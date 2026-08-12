from enterprise_search_evidence import (
    Decision,
    EnterpriseSearchEvidence,
    EnterpriseSearchEvidenceRequest,
)

SNAPSHOT = "a" * 64


def hits() -> list[dict]:
    return [
        {
            "document_id": "d1",
            "source_uri": "https://kb.example/team-a",
            "document_digest": "b" * 64,
            "score": 0.9,
            "indexed_at": 990.0,
            "acl_any": ["group:engineering"],
            "stance": "support",
            "evidence_strength": 0.9,
            "supports_units": ["u1"],
            "contradicts_units": [],
        },
        {
            "document_id": "d2",
            "source_uri": "https://kb.example/public",
            "document_digest": "c" * 64,
            "score": 0.85,
            "indexed_at": 995.0,
            "acl_any": [],
            "stance": "support",
            "evidence_strength": 0.8,
            "supports_units": ["u2"],
            "contradicts_units": [],
        },
    ]


def payload(**changes) -> dict:
    value = {
        "now": 1000.0,
        "actor_id": "person:casey",
        "actor_entitlements": ["group:engineering"],
        "query": "What proves the claim?",
        "claim": "The system has entitlement-aware citations.",
        "claim_units": ["u1", "u2"],
        "index_snapshot_digest": SNAPSHOT,
        "hits": hits(),
        "policy": {
            "min_score": 0.6,
            "max_age_seconds": 100.0,
            "min_supporting_hits": 2,
            "min_supporting_sources": 2,
            "min_claim_coverage": 1.0,
            "max_contradicted_units": 0,
        },
    }
    value.update(changes)
    return value


def evaluate(value=None, *, budget=4.0, not_after=None):
    return EnterpriseSearchEvidence().evaluate(
        EnterpriseSearchEvidenceRequest("claim-1", value or payload(), budget=budget, not_after=not_after)
    )


def test_entitled_fresh_evidence_with_full_claim_coverage_allows():
    receipt = evaluate()
    assert receipt.decision is Decision.ALLOW
    assert receipt.reasons == ("claim_supported_by_entitled_fresh_enterprise_evidence",)
    assert receipt.metrics["claim_coverage"] == 1.0
    assert receipt.metrics["supporting_source_count"] == 2
    assert receipt.result["supported_units"] == ["u1", "u2"]


def test_inaccessible_document_cannot_support_claim():
    value = payload(actor_entitlements=[])
    receipt = evaluate(value)
    assert receipt.decision is Decision.REFUSE
    assert receipt.metrics["inaccessible_hit_count"] == 1
    assert "insufficient_supporting_hits" in receipt.reasons
    assert "insufficient_claim_coverage" in receipt.reasons


def test_stale_document_cannot_support_claim():
    changed = hits()
    changed[0]["indexed_at"] = 800.0
    receipt = evaluate(payload(hits=changed))
    assert receipt.decision is Decision.REFUSE
    assert receipt.metrics["stale_hit_count"] == 1
    assert "insufficient_claim_coverage" in receipt.reasons


def test_low_ranked_document_cannot_supply_coverage():
    changed = hits()
    changed[0]["score"] = 0.2
    receipt = evaluate(payload(hits=changed))
    assert receipt.decision is Decision.REFUSE
    assert "insufficient_supporting_hits" in receipt.reasons
    assert "insufficient_claim_coverage" in receipt.reasons


def test_contradicted_claim_units_refuse():
    changed = hits()
    changed.append(
        {
            "document_id": "d3",
            "source_uri": "https://kb.example/contradiction",
            "document_digest": "d" * 64,
            "score": 0.95,
            "indexed_at": 999.0,
            "acl_any": [],
            "stance": "contradict",
            "evidence_strength": 1.0,
            "supports_units": [],
            "contradicts_units": ["u2"],
        }
    )
    receipt = evaluate(payload(hits=changed))
    assert receipt.decision is Decision.REFUSE
    assert "contradicted_claim_units_exceeded" in receipt.reasons
    assert receipt.result["contradicted_units"] == ["u2"]


def test_extra_hits_do_not_fake_source_diversity():
    changed = hits()
    changed[1]["source_uri"] = changed[0]["source_uri"]
    receipt = evaluate(payload(hits=changed))
    assert receipt.decision is Decision.REFUSE
    assert "insufficient_supporting_sources" in receipt.reasons


def test_unknown_claim_unit_in_hit_refuses():
    changed = hits()
    changed[0]["supports_units"] = ["u3"]
    receipt = evaluate(payload(hits=changed))
    assert receipt.decision is Decision.REFUSE
    assert "hit_0_unknown_claim_units:u3" in receipt.reasons


def test_expected_evidence_digest_binds_actor_entitlements_and_snapshot():
    baseline = evaluate()
    expected = baseline.result["evidence_digest"]
    verified = evaluate(payload(expected_evidence_digest=expected))
    assert verified.decision is Decision.ALLOW

    refused = evaluate(
        payload(actor_entitlements=["group:engineering", "group:admin"], expected_evidence_digest=expected)
    )
    assert refused.decision is Decision.REFUSE
    assert "expected_evidence_digest_mismatch" in refused.reasons


def test_duplicate_document_ids_refuse():
    changed = hits()
    changed[1]["document_id"] = "d1"
    receipt = evaluate(payload(hits=changed))
    assert receipt.decision is Decision.REFUSE
    assert "duplicate_document_id" in receipt.reasons


def test_future_index_timestamp_refuses():
    changed = hits()
    changed[0]["indexed_at"] = 1001.0
    receipt = evaluate(payload(hits=changed))
    assert receipt.decision is Decision.REFUSE
    assert "hit_0_indexed_in_future" in receipt.reasons


def test_request_expiry_refuses():
    receipt = evaluate(not_after=999.0)
    assert receipt.decision is Decision.REFUSE
    assert "request_expired" in receipt.reasons


def test_work_budget_refuses_before_hit_normalization():
    receipt = evaluate(payload(hits=hits() * 40), budget=0.6)
    assert receipt.decision is Decision.REFUSE
    assert "work_budget_exceeded" in receipt.reasons
    assert receipt.metrics["eligible_hit_count"] == 0
