# Submission workflow evaluation

Ground truth = the same screening rules applied to the true resume content, so every difference below comes from extraction.

**Requirement extraction (criteria read from the RFR PDFs): 99% of fields correct**

## 1. True criteria, extracted resumes (resume extraction only)

| Request | Compliance agreement | Points within ±5 | False passes | False fails | Shortlist overlap (top 3) |
|---|---|---|---|---|---|
| RFR-001 | 100% | 100% | none | none | 100% |
| RFR-002 | 100% | 100% | none | none | 100% |
| RFR-003 | 100% | 100% | none | none | 100% |
| RFR-004 | 100% | 100% | none | none | 100% |
| **All** | **100%** | **100%** | **0** | **0** | **100%** |

## 2. Extracted criteria, extracted resumes (end to end)

| Request | Compliance agreement | Points within ±5 | False passes | False fails | Shortlist overlap (top 3) |
|---|---|---|---|---|---|
| RFR-001 | 100% | 100% | none | none | 100% |
| RFR-002 | 100% | 92% | none | none | 100% |
| RFR-003 | 100% | 100% | none | none | 100% |
| RFR-004 | 100% | 100% | none | none | 100% |
| **All** | **100%** | **98%** | **0** | **0** | **100%** |
