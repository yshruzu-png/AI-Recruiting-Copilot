"""
One-time setup for Content Understanding:
  1. Tell Content Understanding which of your model deployments to use (resource "defaults")
  2. Create (or replace) the custom resume analyzer from analyzers/resume-analyzer.json

Usage: python scripts/setup_content_understanding.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot.config import settings  # noqa: E402
from copilot.content_understanding import ContentUnderstandingClient  # noqa: E402

ANALYZER_ID = "resumeAnalyzer"


def main() -> None:
    cu = ContentUnderstandingClient(settings.ai_endpoint)

    print("1/2 Setting default model deployments...")
    defaults = cu.set_default_deployments({
        "gpt-4.1-mini": settings.chat_deployment,
        "text-embedding-3-small": settings.embedding_deployment,
    })
    print("    ", json.dumps(defaults.get("modelDeployments", defaults)))

    print(f"2/2 Creating analyzer '{ANALYZER_ID}' (takes up to a minute)...")
    definition = json.loads((ROOT / "analyzers" / "resume-analyzer.json").read_text())
    cu.create_analyzer(ANALYZER_ID, definition)
    analyzer = cu.get_analyzer(ANALYZER_ID)
    fields = list(analyzer.get("fieldSchema", {}).get("fields", {}))
    print(f"    Ready: {analyzer.get('analyzerId', ANALYZER_ID)} with {len(fields)} fields: {', '.join(fields)}")


if __name__ == "__main__":
    main()
