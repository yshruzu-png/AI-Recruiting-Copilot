"""
Create the Azure AI Search 'candidates' index and load every extracted profile with an embedding.

Prereq: scripts/extract_resumes.py has produced data/extracted/CAND-*.json
Usage:  python scripts/build_search_index.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azure.identity import DefaultAzureCredential  # noqa: E402
from azure.search.documents import SearchClient  # noqa: E402
from azure.search.documents.indexes import SearchIndexClient  # noqa: E402

from copilot.config import settings  # noqa: E402
from copilot.search_index import INDEX_NAME, Embedder, build_index, profile_text, to_search_document  # noqa: E402


def main() -> None:
    profiles = [json.loads(p.read_text()) for p in sorted((ROOT / "data" / "extracted").glob("CAND-*.json"))]
    if not profiles:
        sys.exit("No profiles found. Run scripts/extract_resumes.py first.")

    cred = DefaultAzureCredential()
    print(f"1/3 Creating or updating index '{INDEX_NAME}'...")
    SearchIndexClient(settings.search_endpoint, cred).create_or_update_index(build_index())

    print(f"2/3 Embedding {len(profiles)} profiles with '{settings.embedding_deployment}'...")
    embedder = Embedder(settings.ai_endpoint, settings.embedding_deployment, cred)
    vectors = embedder.embed([profile_text(p) for p in profiles])  # one batched call

    print("3/3 Uploading documents...")
    docs = [to_search_document(p, v) for p, v in zip(profiles, vectors)]
    results = SearchClient(settings.search_endpoint, INDEX_NAME, cred).upload_documents(docs)
    ok = sum(r.succeeded for r in results)
    print(f"Indexed {ok}/{len(docs)} candidates into '{INDEX_NAME}'")
    if ok != len(docs):
        for r in results:
            if not r.succeeded:
                print(f"  {r.key}: {r.error_message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
