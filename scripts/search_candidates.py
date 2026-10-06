"""
Search candidates the way a recruiter would: plain language plus optional filters.

Examples:
    python scripts/search_candidates.py "senior data engineer with Spark and Kafka"
    python scripts/search_candidates.py "LLM and RAG experience on Azure" --role ml_engineer --min-years 3
    python scripts/search_candidates.py "cloud security" --skill "Microsoft Sentinel"
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azure.identity import DefaultAzureCredential  # noqa: E402
from azure.search.documents import SearchClient  # noqa: E402

from copilot.config import settings  # noqa: E402
from copilot.search_index import INDEX_NAME, Embedder, hybrid_search  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--role", dest="role_family", help="data_engineer | ml_engineer | cloud_devops | backend | frontend | security")
    ap.add_argument("--min-years", type=int)
    ap.add_argument("--skill", help="must list this exact skill")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    cred = DefaultAzureCredential()
    client = SearchClient(settings.search_endpoint, INDEX_NAME, cred)
    embedder = Embedder(settings.ai_endpoint, settings.embedding_deployment, cred)
    hits = hybrid_search(client, embedder, args.query, top=args.top, role_family=args.role_family,
                         min_years=args.min_years, skill=args.skill)

    print(f'Top {len(hits)} for: "{args.query}"\n')
    for i, h in enumerate(hits, 1):
        print(f"{i}. {h['id']}  {h['headline']}  ·  {h['years_experience']} yrs  ·  {h['role_family']}"
              f"  (score {h.get('@search.score', 0):.3f})")
        print(f"   Skills: {', '.join(h['skills'][:8])}{' ...' if len(h['skills']) > 8 else ''}")
        if h.get("certifications"):
            print(f"   Certs:  {', '.join(h['certifications'])}")
    if not hits:
        print("No matches. Try removing a filter.")


if __name__ == "__main__":
    main()
