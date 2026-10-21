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

## 006: Content Understanding for resume extraction (not plain OCR + prompt)
**Decision:** Use a custom Content Understanding analyzer with a typed field schema.
**Why:** One managed service handles PDF, Word and scanned images, returns typed fields with confidence scores and source locations, and supports `extract` / `generate` / `classify` methods per field. Low-confidence fields can be routed to a human.
**Trade-off:** Less control than a hand-written prompt; fixed to supported models and regions.

## 007: Send files as base64, not SAS URLs
**Decision:** Download each blob with Entra ID and send the bytes to Content Understanding.
**Why:** Storage has shared keys disabled, so there are no SAS tokens to leak. Fine for resumes (small files).

## 008: Measure extraction against ground truth
**Decision:** Every extraction run is scored (field accuracy, skills precision/recall/F1, per-format breakdown).
**Why:** "It looks right" is not evidence. Numbers show where the analyzer is weak (e.g. scanned images) and prove improvements after schema changes.

## 009: Calculate years of experience in code, not with the LLM
**Decision:** The analyzer extracts each job's start and end dates; Python adds up the months (overlaps counted once, gaps ignored). The model's own estimate is kept only for comparison.
**Why:** On the first test resume the model said 2 years for a candidate with 4 (Mar 2024–Present plus Apr 2022–Sep 2023). LLMs extract text well but are unreliable at arithmetic. Use the model for understanding, and code for calculation.

## 010: Clean certifications against a reference catalog
**Decision:** After extraction, fuzzy-match certifications to a known catalog (difflib, 90% similarity) and drop items that duplicate an Education entry.
**Why:** The first full run scored 87% F1 on certifications. Three errors were the same issue: the PDF text layer read "Azure **AI** Engineer" as "Azure **Al** Engineer" (capital I vs lowercase l). One was a bootcamp certificate counted twice. Deterministic post-processing fixes both without asking the model to guess.

## 011: Hybrid search (keyword + vector) instead of vector-only
**Decision:** Query AI Search with BM25 keywords and an embedding at the same time; AI Search merges them with Reciprocal Rank Fusion.
**Why:** Recruiters search for exact terms ("Kafka", "CISSP") and for meaning ("someone who has built data pipelines"). Keywords catch exact skills; vectors catch related ones. Filters (career track, minimum years, required skill) handle hard requirements.

## 012: Never embed names, contact details or protected information
**Decision:** The embedded/searchable text holds title, career track, years, skills, certifications, job titles and degrees only. Name and email are stored for display but are not searchable.
**Why:** If a name or date of birth is in the vector, it can quietly influence similarity. Keeping it out is the first layer of bias-aware screening, before the Week 4 workflow.

## 013: Microsoft Agent Framework with a Foundry chat client
**Decision:** Build the agent with `agent_framework.Agent` and `FoundryChatClient` (project endpoint, Entra ID). Tools are plain Python methods wrapped with `@tool`.
**Why:** It is Microsoft's supported successor to Semantic Kernel and AutoGen agents, it works with any chat client (so tests can swap in a scripted fake), and Week 4 workflows and Week 6 tracing build on the same package.

## 014: The model explains, code scores
**Decision:** The agent ranks by calling `rank_candidates_for_job`, which scores candidates in Python. The model writes the explanation.
**Why:** Same lesson as decision 009. An LLM asked to rank 20 profiles will be inconsistent between runs and can't show its working. A formula gives the same answer every time, each point can be explained ("missing Azure Data Factory"), and it can be audited. The formula matches the ground-truth baseline, and a test proves it reproduces the baseline scores exactly.

## 015: Retrieve, then score
**Decision:** The ranking tool pulls the top 20 from hybrid search, then scores only those.
**Why:** It's how this would scale to 40,000 resumes instead of 40: search narrows the field cheaply, then the exact scoring runs on a shortlist. The cost is that a strong candidate search misses can't be ranked, which the evaluation's baseline-overlap number measures.

## 016: Blind profiles at the tool boundary
**Decision:** Tools return only skills, titles, companies, dates, certifications and degree names. Names, email, phone, location, graduation years, raw resume text and protected flags never reach the model.
**Why:** Instructions alone are not a control: a model can be talked out of a rule. If the model never receives a candidate's age or name, no prompt can make it rank on them. Graduation year is dropped because it's a proxy for age; location because it can be a proxy for origin and isn't needed for a skills match.

## 017: Evaluate the agent, not just the parts
**Decision:** A fixed set of 10 questions (ranking, fairness probes, an impossible role) runs against the live agent and is scored on tool use, grounding (only cites IDs a tool returned), baseline agreement, no names, declining protected-ground requests and admitting "no match".
**Why:** Component tests passed in Week 2, but an agent can still pick the wrong tool, invent a candidate or comply with a biased request. These are the failures a recruiting client would care about.
