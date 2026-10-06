"""
Reference catalog of known certifications, used to clean up extraction noise.

Example: in some PDFs the text layer reads "Azure AI Engineer" as "Azure Al Engineer"
(capital I vs lowercase l look identical in many fonts). Fuzzy-matching against a catalog
fixes this kind of error without asking the model to guess.
"""
from __future__ import annotations

import difflib

KNOWN_CERTIFICATIONS = [
    "Microsoft Certified: Azure AI Engineer Associate",
    "Microsoft Certified: Azure AI Fundamentals",
    "Microsoft Certified: Azure Data Scientist Associate",
    "Microsoft Certified: Azure Administrator Associate",
    "Microsoft Certified: Azure Developer Associate",
    "Microsoft Certified: DevOps Engineer Expert",
    "Microsoft Certified: Fabric Data Engineer Associate",
    "Microsoft Certified: Security Operations Analyst Associate",
    "Microsoft Certified: Cybersecurity Architect Expert",
    "Databricks Certified Data Engineer Associate",
    "HashiCorp Certified: Terraform Associate",
    "Certified Kubernetes Administrator",
    "Oracle Certified Professional: Java SE Developer",
    "Meta Front-End Developer Professional Certificate",
    "CISSP",
    "CompTIA Security+",
]
_BY_LOWER = {c.lower(): c for c in KNOWN_CERTIFICATIONS}


def canonical_certification(name: str, cutoff: float = 0.9) -> str:
    """Return the catalog spelling if `name` is a near-exact match, otherwise `name` unchanged."""
    match = difflib.get_close_matches(name.lower(), list(_BY_LOWER), n=1, cutoff=cutoff)
    return _BY_LOWER[match[0]] if match else name


def clean_certifications(certs: list[str], education: list[dict]) -> list[str]:
    """Canonicalize spellings, drop duplicates, and drop items that are really education entries."""
    degrees = {str(e.get("Degree", "")).strip().lower() for e in education or []}
    out: list[str] = []
    for c in certs:
        if c.strip().lower() in degrees:
            continue  # e.g. a bootcamp certificate already listed under Education
        canon = canonical_certification(c)
        if canon not in out:
            out.append(canon)
    return out
