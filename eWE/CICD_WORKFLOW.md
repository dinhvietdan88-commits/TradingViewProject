# CI/CD Workflow Guide

## Pipeline Architecture

```
Feature Branch → Push → CI Pull Request Pipeline (ci.yml)
                          ├── Detect Changes
                          ├── Lint & Security Scan
                          └── Tests (2 parallel matrix runners)
                                ├── Fast: Unit + Integration + System (540 tests)
                                └── Browser: E2E + Security (35 tests)

PR Merge → main → CI/CD Production Pipeline (deploy.yml)
                    ├── Detect Changes (+ 3-Tier Deploy Tiers)
                    ├── Lint & Security Scan
                    ├── Tests (cached — skip if same code hash)
                    ├── Build & Push Docker Images (3 parallel matrix)
                    │     ├── VBS (Server A)
                    │     ├── Execution (Server B)
                    │     └── Analyzer (Server C)
                    ├── Deploy (3-Tier Strategy, parallel)
                    │     ├── Server A (Gateway)     [T0/T1/T2]
                    │     ├── Server B (Execution)   [T0/T1/T2]
                    │     └── Server C (AI Core)     [T0/T1/T2]
                    └── Pipeline Summary & Telegram Alert
```

## Developer Workflow

### 1. Create Feature Branch
```bash
git checkout -b feature/my-feature
```

### 2. Develop & Commit
```bash
git add .
git commit -m "feat(scope): description"
```

### 3. Push Branch (triggers CI)
```bash
git push origin feature/my-feature
```

### 4. Create Pull Request
- Go to GitHub → Create PR targeting `main`
- CI Pull Request Pipeline runs automatically
- Review test results before merging

### 5. Merge PR (triggers Deploy)
- Merge PR on GitHub
- CI/CD Production Pipeline runs automatically
- 3-Tier Strategy determines deploy scope per server

## 3-Tier Deploy Strategy

| Tier | Action | When |
|------|--------|------|
| **T0** | Skip (no deploy) | Only docs, tests, or CI config changed |
| **T1** | `git pull` + `docker restart` | Config or deploy files changed |
| **T2** | `docker pull` + `docker up -d` | Source code / Dockerfile changed |

### Safety Nets
- `[force deploy]` in commit message → Tier 2 ALL servers
- Merge commits → Tier 2 ALL servers
- Unknown file patterns → Tier 1 ALL servers (safe fallback)

### Override
```bash
git commit -m "fix(vbs): patch X [force deploy]"
```

## Telegram Notifications
Deploy results are sent to Telegram with per-server tier labels:
```
✅ CI/CD Pipeline Deployment Report
• Server A (Gateway) [T2 Full]: 🟢 SUCCESS
• Server C (AI Core) [T0 Skip]: 🟡 SKIPPED
• Server B (Execution) [T0 Skip]: 🟡 SKIPPED
```
