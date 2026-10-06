# Candidate search evaluation

Each job description is used as the search query (hybrid: keyword + vector).

- **Family precision@5:** 100% of the top 5 candidates are in the job's career track
- **Baseline overlap@10:** 80% agreement with a transparent skill-overlap baseline

| Job | Family precision@5 | Baseline overlap@10 | Top 5 |
|---|---|---|---|
| JD-001 Senior Data Engineer | 100% | 70% | CAND-036, CAND-015, CAND-012, CAND-037, CAND-024 |
| JD-002 AI Engineer (Generative AI) | 100% | 80% | CAND-031, CAND-004, CAND-028, CAND-010, CAND-039 |
| JD-003 DevOps Engineer | 100% | 100% | CAND-032, CAND-019, CAND-035, CAND-013, CAND-027 |
| JD-004 Intermediate Java Developer | 100% | 60% | CAND-003, CAND-033, CAND-026, CAND-020, CAND-009 |
| JD-005 Cloud Security Engineer | 100% | 90% | CAND-016, CAND-011, CAND-018, CAND-005, CAND-021 |
