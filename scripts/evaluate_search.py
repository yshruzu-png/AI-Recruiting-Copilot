"""
Use each job description as a search query and score the results.
Writes docs/eval/search_report.md.

Usage: python scripts/evaluate_search.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azure.identity import DefaultAzureCredential  # noqa: E402
from azure.search.documents import SearchClient  # noqa: E402

from copilot.config import settings  # noqa: E402
from copilot.evaluation import search_metrics, search_to_markdown  # noqa: E402
from copilot.search_index import INDEX_NAME, Embedder, hybrid_search  # noqa: E402


def main() -> None:
    gt = json.loads((ROOT / "data" / "synthetic" / "ground_truth.json").read_text())
    cred = DefaultAzureCredential()
    client = SearchClient(settings.search_endpoint, INDEX_NAME, cred)
    embedder = Embedder(settings.ai_endpoint, settings.embedding_deployment, cred)

    results = {}
    for job in gt["jobs"]:
        query = (ROOT / "data" / "synthetic" / "job-descriptions" / f"{job['id']}.md").read_text()
        hits = hybrid_search(client, embedder, query, top=10)
        results[job["id"]] = [h["id"] for h in hits]
        print(f"  {job['id']} {job['title']:<30} -> {', '.join(results[job['id']][:5])}")

    m = search_metrics(results, gt["jobs"], gt["candidates"])
    out = ROOT / "docs" / "eval" / "search_report.md"
    out.write_text(search_to_markdown(m))
    print(f"\nFamily precision@5   {m['family_precision@5']:.0%}")
    print(f"Baseline overlap@10  {m['baseline_overlap@10']:.0%}")
    print(f"Report: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
