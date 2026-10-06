"""
Azure AI Search: candidate index definition, document building, embeddings and hybrid search.

Responsible-AI choice: the text we embed and search on contains skills, titles, experience and
education only. Names, contact details and protected information (date of birth, marital status,
photo) are never embedded, so they cannot influence similarity ranking.
"""
from __future__ import annotations

from typing import Any

INDEX_NAME = "candidates"
EMBED_DIMENSIONS = 1536  # text-embedding-3-small
VECTOR_PROFILE = "candidate-vector-profile"


# ---------------------------------------------------------------------------
# Index definition
# ---------------------------------------------------------------------------
def build_index(name: str = INDEX_NAME):
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration, SearchableField, SearchField, SearchFieldDataType,
        SearchIndex, SimpleField, VectorSearch, VectorSearchProfile,
    )
    S = SearchFieldDataType
    fields = [
        SimpleField(name="id", type=S.String, key=True),
        # stored for display to the recruiter, NOT used for ranking
        SimpleField(name="name", type=S.String),
        SimpleField(name="email", type=S.String),
        SimpleField(name="source_file", type=S.String),
        SearchableField(name="headline", type=S.String),
        SimpleField(name="role_family", type=S.String, filterable=True, facetable=True),
        SimpleField(name="years_experience", type=S.Int32, filterable=True, sortable=True, facetable=True),
        SearchableField(name="skills", collection=True, filterable=True, facetable=True),
        SearchableField(name="certifications", collection=True, filterable=True, facetable=True),
        SimpleField(name="location", type=S.String, filterable=True, facetable=True),
        SearchableField(name="profile_text", type=S.String),
        SearchField(
            name="profile_vector",
            type=S.Collection(S.Single),
            searchable=True,
            vector_search_dimensions=EMBED_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE,
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name=VECTOR_PROFILE, algorithm_configuration_name="hnsw")],
    )
    return SearchIndex(name=name, fields=fields, vector_search=vector_search)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def profile_text(profile: dict[str, Any]) -> str:
    """Searchable/embeddable description of a candidate: skills and experience only (no PII)."""
    jobs = "; ".join(
        f"{j.get('JobTitle', '')} ({j.get('StartDate', '')} - {j.get('EndDate', '')})"
        for j in profile.get("work_history") or []
    )
    edu = "; ".join(f"{e.get('Degree', '')}" for e in profile.get("education") or [])
    parts = [
        f"Current title: {profile.get('headline') or ''}",
        f"Career track: {(profile.get('role_family') or '').replace('_', ' ')}",
        f"Years of experience: {profile.get('years_experience')}",
        f"Skills: {', '.join(profile.get('skills') or [])}",
        f"Certifications: {', '.join(profile.get('certifications') or []) or 'none'}",
        f"Work history: {jobs}",
        f"Education: {edu}",
    ]
    return "\n".join(parts)


def to_search_document(profile: dict[str, Any], vector: list[float] | None = None) -> dict[str, Any]:
    years = profile.get("years_experience")
    doc = {
        "id": profile["id"],
        "name": profile.get("name"),
        "email": profile.get("email"),
        "source_file": profile.get("source_file"),
        "headline": profile.get("headline"),
        "role_family": profile.get("role_family"),
        "years_experience": int(years) if isinstance(years, (int, float)) else None,
        "skills": profile.get("skills") or [],
        "certifications": profile.get("certifications") or [],
        "location": profile.get("location"),
        "profile_text": profile_text(profile),
    }
    if vector is not None:
        doc["profile_vector"] = vector
    return doc


# ---------------------------------------------------------------------------
# Embeddings (Azure OpenAI through the Foundry resource, Entra ID auth)
# ---------------------------------------------------------------------------
class Embedder:
    def __init__(self, endpoint: str, deployment: str, credential=None):
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            credential or DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        self.client = AzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=token_provider,
                                  api_version="2024-10-21")
        self.deployment = deployment

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.deployment, input=texts)
        return [d.embedding for d in resp.data]


# ---------------------------------------------------------------------------
# Hybrid search
# ---------------------------------------------------------------------------
def build_filter(role_family: str | None = None, min_years: int | None = None,
                 skill: str | None = None) -> str | None:
    clauses = []
    if role_family:
        clauses.append(f"role_family eq '{role_family}'")
    if min_years is not None:
        clauses.append(f"years_experience ge {int(min_years)}")
    if skill:
        safe = skill.replace("'", "''")
        clauses.append(f"skills/any(s: s eq '{safe}')")
    return " and ".join(clauses) or None


def hybrid_search(search_client, embedder: Embedder, query: str, top: int = 5, **filters) -> list[dict]:
    """Keyword (BM25) + vector similarity, merged by Reciprocal Rank Fusion inside AI Search."""
    from azure.search.documents.models import VectorizedQuery

    vector = embedder.embed([query])[0]
    results = search_client.search(
        search_text=query,
        vector_queries=[VectorizedQuery(vector=vector, k_nearest_neighbors=50, fields="profile_vector")],
        filter=build_filter(**filters),
        select=["id", "name", "headline", "role_family", "years_experience", "skills", "certifications"],
        top=top,
    )
    return [dict(r) for r in results]
