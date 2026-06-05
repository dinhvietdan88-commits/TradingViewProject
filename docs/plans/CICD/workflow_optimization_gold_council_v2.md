# CI/CD Optimization — Gold Council Session (2026-06-05)

## Summary

Phiên làm việc này tối ưu hoá toàn bộ GitHub Actions pipeline của TradingViewProject thông qua 3 quyết định kiến trúc từ Gold Council (E5 — Consensus).

---

## Gold Council Verdicts

### Q1: `hotfix/*` Branch Convention — **APPROVED**
- `hotfix/*` → `quick` + `tests-safety` (bắt buộc, không skip security)
- Guard: diff > 300 lines → auto-upgrade to `standard`
- Deploy thẳng production sau ~5 min

### Q2: `workflow_run` Trigger — **APPROVED (Clean Causal Dependency)**
- `deploy.yml` trigger: `workflow_run` (primary) + `push` (fallback `[force deploy]`)
- Loại bỏ race condition của cache sentinel approach
- `check-ci-gate` job vẫn có 3-tier fallback logic:
  1. `workflow_run.conclusion == 'success'` → allow
  2. `[force deploy]` / merge commit → bypass
  3. Sentinel cache hit → allow

### Q3: CI trên Feature Branches — **APPROVED (Smart Depth)**
- `feat/*` → `quick` (~3 min)
- `fix/*` → `standard` (~8 min)
- `hotfix/*` → `quick+safety` (~5 min, deploy enabled)
- `release/*` → `full` (~20 min)

---

## Architecture

```
                     PUSH / PR EVENT
                           │
               ┌───────────┴──────────────┐
               │     ci.yml — CLASSIFY     │
               │  (tier detection + branch) │
               └───────────────────────────┘
                           │
              ┌────────────┼──────────────────────────┐
              │            │                          │
           TIER 0       TIER 1                   TIER 2/3
          (docs)        (config)               (code/deps)
           SKIP         LINT only              depth by branch
              │            │                          │
              └────────────┴──────────────────────────┘
                           │
                    _ci-gate.yml (reusable)
                    ┌──────────────────────┐
                    │  lint                │
                    │  tests-fast          │ ← quick/standard/full
                    │  tests-parity        │ ← standard/full
                    │  tests-safety        │ ← quick/standard/full
                    │  tests-e2e           │ ← full only
                    │  tests-advanced      │ ← full only
                    │  gate-result         │ ← always
                    └──────────────────────┘
                           │
                  (sentinel cache written)
                           │
              ┌────────────┴───────────────┐
              │  deploy.yml (workflow_run) │
              │  check-ci-gate (5 min)     │
              │  build-images (parallel)   │
              │  deploy-server-a/b/c       │
              └────────────────────────────┘
```

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `.github/workflows/_ci-gate.yml` | **NEW** | Reusable CI gate — 7 jobs, depth-controlled |
| `.github/workflows/ci.yml` | **REWRITE** | Smart classify (199→153 lines) |
| `.github/workflows/deploy.yml` | **REFACTOR** | Remove ~150 duplicate lines, `workflow_run` trigger |
| `.github/workflows/security.yml` | **PATCH** | `check-code-changed` pre-filter |
| `.github/workflows/staging.yml` | **PATCH** | Code path filter, skip docs |
| `.github/workflows/automation.yml` | **NEW** | PR/Issue automation (labeler, stale, greetings) |
| `.github/labeler.yml` | **NEW** | Path-based PR label mapping |

---

## Change Tier System

| Tier | Files Changed | Action |
|------|--------------|--------|
| T0 | docs/*.md, pine/*, scratch/* | **SKIP** — 0 runners |
| T1 | config, .env.example, workflows | **LINT only** |
| T2 | server/*.py, vbs/* | **depth by branch** |
| T3 | requirements*.txt, Dockerfile | **FULL** |

---

## Branch → Test Depth Matrix

| Branch | Depth | Runners | Time | Deploy |
|--------|-------|---------|------|--------|
| `feat/*` | quick | 2 | ~3 min | ❌ |
| `fix/*` | standard | 3 | ~8 min | ❌ |
| `hotfix/*` | quick+safety | 3 | ~5 min | ✅ prod |
| `develop` | standard | 3 | ~8 min | ❌ |
| `main` (PR) | standard | 3 | ~8 min | ❌ |
| `main` (merge) | via cache | 1 | ~2 min | ✅ prod |
| `release/*` | full | 6 | ~20 min | ✅ prod |

---

## Cache Architecture (3 Layers)

```
LAYER 1: Code Hash Sentinel
  key:  test-passed-{stage}-{sha256_of_py_files}
  TTL:  7 days
  Shared: ci.yml ──► deploy.yml (same hash key)
  Saving: 100% test time when code unchanged

LAYER 2: uv Package Cache
  key:  Linux-uv-{YYYY-WNN}-{hash_requirements}
  TTL:  7 days (weekly rotation)
  Saving: ~2 min per runner

LAYER 3: Playwright Browser Cache
  key:  Linux-playwright-{hash_requirements}
  TTL:  14 days
  Saving: ~3 min per E2E run
```

---

## Savings Estimate

| Scenario | Before | After | Saved |
|----------|--------|-------|-------|
| Push docs-only | 5 runners | 0 runners | **100%** |
| Code push (merge) | 10 runners | 4 runners | **~60%** |
| Hotfix push | 10 runners | 3 runners | **~70%** |
| Monthly estimate | ~800 min | ~250 min | **~69%** |

---

## Validation

```
✅ YAML Syntax     — all 5 workflow files valid
✅ Stale refs      — 0 occurrences of ci-lint-security / ci-tests
✅ check-ci-gate   — 9 references in deploy.yml
✅ workflow_run    — trigger confirmed
✅ reusable call   — ci.yml → ./.github/workflows/_ci-gate.yml
✅ Gold Council    — all 3 Q&A verdicts implemented
```
