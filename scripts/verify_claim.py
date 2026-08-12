#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_search_evidence import Decision, EnterpriseSearchEvidence, EnterpriseSearchEvidenceRequest


def _payload() -> dict:
    return {
        "now": 1000.0,
        "actor_id": "person:demo",
        "actor_entitlements": ["group:engineering"],
        "query": "What proves the claim?",
        "claim": "The system preserves entitlement-aware citations.",
        "claim_units": ["u1", "u2"],
        "index_snapshot_digest": "a" * 64,
        "hits": [
            {
                "document_id": "d1",
                "source_uri": "https://kb.example/private",
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
        ],
        "policy": {
            "min_score": 0.6,
            "max_age_seconds": 100.0,
            "min_supporting_hits": 2,
            "min_supporting_sources": 2,
            "min_claim_coverage": 1.0,
            "max_contradicted_units": 0,
        },
    }


def main() -> int:
    engine = EnterpriseSearchEvidence()
    baseline = engine.evaluate(EnterpriseSearchEvidenceRequest("operate", _payload(), budget=4.0))
    if baseline.decision is not Decision.ALLOW:
        print(json.dumps(baseline.as_dict(), indent=2, sort_keys=True))
        return 2

    inaccessible_payload = deepcopy(_payload())
    inaccessible_payload["actor_entitlements"] = []
    inaccessible = engine.evaluate(
        EnterpriseSearchEvidenceRequest("operate", inaccessible_payload, budget=4.0)
    )

    stale_payload = deepcopy(_payload())
    stale_payload["hits"][0]["indexed_at"] = 800.0
    stale = engine.evaluate(EnterpriseSearchEvidenceRequest("operate", stale_payload, budget=4.0))

    rebound_payload = _payload()
    rebound_payload["expected_evidence_digest"] = baseline.result["evidence_digest"]
    rebound = engine.evaluate(EnterpriseSearchEvidenceRequest("operate", rebound_payload, budget=4.0))

    print(json.dumps({
        "baseline": baseline.as_dict(),
        "inaccessible": inaccessible.as_dict(),
        "stale": stale.as_dict(),
        "rebound": rebound.as_dict(),
    }, indent=2, sort_keys=True))

    if inaccessible.decision is not Decision.REFUSE:
        return 3
    if stale.decision is not Decision.REFUSE:
        return 4
    if rebound.decision is not Decision.ALLOW:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
