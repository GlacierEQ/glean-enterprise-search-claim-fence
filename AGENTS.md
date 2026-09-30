# AGENTS.md — glean-enterprise-search-claim-fence

**Company:** Glean
**Domain:** Enterprise Data Platform & Authority Governance

## Quick Rules
- **Test command:** `PYTHONPATH=src pytest tests/ -v`
- **Lint:** `ruff check src/ tests/`
- **No drive-by edits** — load the skill first.

## Architecture
- `src/glean_enterprise_search_claim_fence/core.py` — Domain logic (Enterprise Data Platform & Authority Governance)
- `tests/` — Verified test suite
- `.github/workflows/ci.yml` — Enforced CI pipeline
