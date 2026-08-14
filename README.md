# Enterprise Search Claim Fence

Independent GlacierEQ specialist component aligned to enterprise-search evidence problems. It is not affiliated with, endorsed by, employed by, or deployed at Glean.

## Problem owned

Enterprise answers can appear supported while depending on documents the requesting actor cannot access, stale retrieval results, weak evidence, or incomplete claim coverage. This repository provides a deterministic evidence gate over normalized search results and explicit ACL metadata.

## Implemented mechanism

`src/enterprise_search_evidence.py` evaluates one actor/query/claim against a bounded result set and policy. It:

- binds actor identity and entitlements into the evidence decision;
- excludes ACL-inaccessible, stale, or below-threshold documents;
- owns freshness time at the evaluator boundary; callers cannot override evaluation time in the payload, while tests may inject a deterministic clock;
- maps supporting and contradicting metadata to explicit claim units and refuses contradiction even when a hit's coarse stance label says `support`;
- enforces minimum supporting-hit, source-diversity, and full claim-coverage policy;
- permits caller policy to tighten security thresholds, never weaken the verifier's minimum score, evidence-strength, or claim-coverage floors;
- rejects excessive contradiction;
- binds decisions to immutable document and index-snapshot digests, including actor-entitlement identity;
- supports expected-evidence rebinding to detect result, entitlement, or snapshot mutation;
- enforces the aggregate input-size ceiling at the library boundary as well as the CLI boundary;
- normalizes unreadable input failures without echoing local filesystem paths;
- rejects malformed, over-budget, expired, duplicate, or out-of-range inputs fail-closed;
- emits deterministic ALLOW/REFUSE receipts with bounded metrics and evidence identity.

The provider adapter boundary is explicit: retrieval/authentication is supplied externally. This code does not connect to Glean, use proprietary APIs, or claim provider attestation.

## Reproduce

```bash
python -m pytest -q
python scripts/verify_claim.py
```

Repository-native CI runs the same full test suite plus the direct verification scenario on Python 3.12.

## Role and unique value

Role: **specialist component / entitlement-aware enterprise-search evidence verifier**.

Its distinct value versus generic or hybrid-search claim fences is actor-specific authorization and claim-unit coverage. Search ranking is input evidence, not the mechanism owned here.

Reusable capability: ACL-aware evidence eligibility + claim-unit coverage + trusted freshness evaluation + bounded library evaluation + content-addressed evidence rebinding.

## Truth boundary

- No Glean affiliation, employment, endorsement, proprietary data, or production deployment.
- No live provider retrieval, provider authentication, customer impact, latency, scale, or revenue claim.
- Passing repository tests prove only the deterministic local evidence contract at the exact tested source revision.
- Deployment/runtime-provider proof is not required for this local verifier; a real provider adapter would require separate evidence.

## Excellence cursor

Keep the full deterministic/adversarial suite passing on each source revision, preserve ACL, policy-floor, evaluator-time, aggregate-size, contradiction-accounting, safe-error, entitlement-rebinding, and evidence-rebinding boundaries, and only add provider integration when it can be authenticated and proven separately.
