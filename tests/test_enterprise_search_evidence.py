from enterprise_search_evidence import Decision, EnterpriseSearchEvidence, EnterpriseSearchEvidenceRequest

SNAPSHOT = "a" * 64

def hits() -> list[dict]:
    return [
        {"document_id":"d1","source_uri":"https://kb.example/team-a","document_digest":"b"*64,"score":0.9,"indexed_at":990.0,"acl_any":["group:engineering"],"stance":"support","evidence_strength":0.9,"supports_units":["u1"],"contradicts_units":[]},
        {"document_id":"d2","source_uri":"https://kb.example/public","document_digest":"c"*64,"score":0.85,"indexed_at":995.0,"acl_any":[],"stance":"support","evidence_strength":0.8,"supports_units":["u2"],"contradicts_units":[]},
    ]

def payload(**changes) -> dict:
    value={"now":1000.0,"actor_id":"person:casey","actor_entitlements":["group:engineering"],"query":"What proves the claim?","claim":"The system has entitlement-aware citations.","claim_units":["u1","u2"],"index_snapshot_digest":SNAPSHOT,"hits":hits(),"policy":{"min_score":0.6,"min_evidence_strength":0.5,"max_age_seconds":100.0,"min_supporting_hits":2,"min_supporting_sources":2,"min_claim_coverage":1.0,"max_contradicted_units":0}}
    value.update(changes); return value

def evaluate(value=None, *, budget=4.0, not_after=None): return EnterpriseSearchEvidence().evaluate(EnterpriseSearchEvidenceRequest("claim-1", value or payload(), budget=budget, not_after=not_after))

def test_entitled_fresh_evidence_with_full_claim_coverage_allows():
    r=evaluate(); assert r.decision is Decision.ALLOW; assert r.metrics["claim_coverage"]==1.0; assert r.metrics["supporting_source_count"]==2; assert r.result["supported_units"]==["u1","u2"]

def test_receipt_does_not_expose_manifest_or_acl_metadata():
    r=evaluate(); assert "manifest" not in r.result; serialized=str(r.as_dict()); assert "group:engineering" not in serialized; assert "https://kb.example/team-a" not in serialized

def test_inaccessible_document_cannot_support_claim():
    r=evaluate(payload(actor_entitlements=[])); assert r.decision is Decision.REFUSE; assert r.metrics["inaccessible_hit_count"]==1; assert "insufficient_claim_coverage" in r.reasons

def test_stale_document_cannot_support_claim():
    h=hits(); h[0]["indexed_at"]=800.0; r=evaluate(payload(hits=h)); assert r.decision is Decision.REFUSE; assert r.metrics["stale_hit_count"]==1

def test_low_ranked_document_cannot_supply_coverage():
    h=hits(); h[0]["score"]=0.2; r=evaluate(payload(hits=h)); assert r.decision is Decision.REFUSE; assert "insufficient_claim_coverage" in r.reasons

def test_weak_evidence_cannot_supply_coverage():
    h=hits(); h[0]["evidence_strength"]=0.000001; r=evaluate(payload(hits=h)); assert r.decision is Decision.REFUSE; assert r.metrics["weak_evidence_hit_count"]==1; assert "insufficient_claim_coverage" in r.reasons

def test_contradicted_claim_units_refuse():
    h=hits(); h.append({"document_id":"d3","source_uri":"https://kb.example/contradiction","document_digest":"d"*64,"score":0.95,"indexed_at":999.0,"acl_any":[],"stance":"contradict","evidence_strength":1.0,"supports_units":[],"contradicts_units":["u2"]}); r=evaluate(payload(hits=h)); assert r.decision is Decision.REFUSE; assert "contradicted_claim_units_exceeded" in r.reasons

def test_extra_hits_do_not_fake_source_diversity():
    h=hits(); h[1]["source_uri"]=h[0]["source_uri"]; assert "insufficient_supporting_sources" in evaluate(payload(hits=h)).reasons

def test_unknown_claim_unit_in_hit_refuses():
    h=hits(); h[0]["supports_units"]=["u3"]; assert "hit_0_unknown_claim_units:u3" in evaluate(payload(hits=h)).reasons

def test_expected_evidence_digest_binds_actor_entitlements_and_snapshot():
    expected=evaluate().result["evidence_digest"]; assert evaluate(payload(expected_evidence_digest=expected)).decision is Decision.ALLOW
    r=evaluate(payload(index_snapshot_digest="f"*64, expected_evidence_digest=expected)); assert r.decision is Decision.REFUSE; assert "expected_evidence_digest_mismatch" in r.reasons

def test_duplicate_document_ids_refuse():
    h=hits(); h[1]["document_id"]="d1"; assert "duplicate_document_id" in evaluate(payload(hits=h)).reasons

def test_future_index_timestamp_refuses():
    h=hits(); h[0]["indexed_at"]=1001.0; assert "hit_0_indexed_in_future" in evaluate(payload(hits=h)).reasons

def test_request_expiry_refuses(): assert "request_expired" in evaluate(not_after=999.0).reasons

def test_work_budget_refuses_before_hit_normalization():
    r=evaluate(payload(hits=hits()*40),budget=0.6); assert r.decision is Decision.REFUSE; assert "work_budget_exceeded" in r.reasons; assert r.metrics["eligible_hit_count"]==0
