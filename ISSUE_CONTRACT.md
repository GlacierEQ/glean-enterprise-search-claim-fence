# Issue contract — Enterprise Search Claim Fence

## Problem
Workplace answers mix permissioned retrieval with uncited model fill.

## Desired outcome
A bounded, open, testable implementation of **Enterprise Search Claim Fence** that demonstrates Attach ACL-bound evidence digests to every answer claim; drop claims without permitted sources.

## Non-goals
- Glean affiliation or proprietary integration
- Portfolio-wide scale/performance claims
- UI marketing site

## Acceptance
1. Mechanism module implements allow + refuse with structured receipts
2. pytest behavioral suite green
3. operate.py cold-start produces JSON receipt
4. Non-affiliation disclaimer preserved
