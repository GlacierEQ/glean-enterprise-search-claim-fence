# Issue contract — Enterprise Search Claim Fence

## Problem
Workplace answers can appear supported while relying on stale, inaccessible, weak, or incomplete evidence.

## Desired outcome
A bounded, deterministic entitlement-aware evidence verifier that accepts normalized search results plus ACL metadata and emits content-addressed ALLOW/REFUSE receipts.

## Owned mechanism
- actor identity + entitlement binding
- ACL-aware evidence eligibility
- freshness and score thresholds
- explicit claim-unit support/contradiction mapping
- source diversity and minimum claim coverage
- expected-evidence digest rebinding
- strict bounded input validation and fail-closed behavior

Provider retrieval and authentication remain adapter responsibilities.

## Non-goals
- Glean affiliation or proprietary integration
- live provider retrieval without an authenticated adapter
- provider attestation
- production/customer/scale claims without separate receipts
- generic promotion authority

## Acceptance
1. canonical mechanism is `src/enterprise_search_evidence.py` with no competing scaffold implementation;
2. `python -m pytest -q` passes the complete repository test surface;
3. `python scripts/verify_claim.py` exercises allow, ACL denial, stale evidence, and evidence rebinding;
4. repository-native exact-head CI passes both commands;
5. README, package metadata, and machine target contract describe the same role and nonclaims.
