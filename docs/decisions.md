# Design decisions

A running log of the main choices and the reasons behind them. Useful for interviews: "Why did you do it this way?"

## 001: No API keys anywhere
**Decision:** Disable local auth on Foundry, AI Search and Storage. Use Entra ID (developer `az login`, app managed identity) with RBAC.
**Why:** Leaked keys are one of the most common cloud security incidents. RBAC gives least privilege and an audit trail.
**Trade-off:** A bit more setup (role assignments, propagation delays).

## 002: Synthetic data only
**Decision:** Generate fake resumes with a seeded generator instead of collecting real ones.
**Why:** Resumes are personal information. Synthetic data also comes with ground truth, which makes evaluation possible.
**Trade-off:** Less messy than real resumes. Scanned PNGs and mixed formats add some realism back.

## 003: Planted protected attributes
**Decision:** About 40% of resumes include a date of birth, marital status or a photo marker.
**Why:** To prove the blind-screening step removes them before scoring, and to measure that it does.

## 004: Terraform with azapi for Foundry
**Decision:** Use `azurerm` for standard resources and `azapi` for the Foundry account and project.
**Why:** `azapi` exposes `allowProjectManagement` and new API versions as soon as they ship.

## 005: AI Search Free tier for development
**Decision:** Start on Free and move to Basic only if the semantic ranker is needed for the demo.
**Why:** Keeps idle cost close to zero. Free tier limits (50 MB, 3 indexes) are fine for 40 resumes.
