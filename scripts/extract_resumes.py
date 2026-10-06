"""
Run every resume in Blob Storage through the Content Understanding resume analyzer
and save one clean JSON profile per candidate to data/extracted/.

Usage:
    python scripts/extract_resumes.py              # all resumes
    python scripts/extract_resumes.py --limit 3    # quick test on 3 files
"""
import argparse
import json
import mimetypes
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azure.identity import DefaultAzureCredential  # noqa: E402
from azure.storage.blob import BlobServiceClient  # noqa: E402

from copilot.config import settings  # noqa: E402
from copilot.content_understanding import ContentUnderstandingClient  # noqa: E402
from copilot.profiles import to_profile  # noqa: E402

ANALYZER_ID = "resumeAnalyzer"
OUT = ROOT / "data" / "extracted"
mimetypes.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only process the first N resumes")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", nargs="+", default=[], help="only these candidate IDs, e.g. --only CAND-013")
    ap.add_argument("--from-raw", action="store_true",
                    help="rebuild profiles from saved raw results without calling Azure (free)")
    args = ap.parse_args()

    if args.from_raw:
        raws = sorted((OUT / "raw").glob("CAND-*.json"))
        for raw in raws:
            profile = to_profile(raw.stem, raw.stem, json.loads(raw.read_text()))
            (OUT / f"{raw.stem}.json").write_text(json.dumps(profile, indent=2))
        print(f"Rebuilt {len(raws)} profiles from {OUT / 'raw'}")
        return

    cred = DefaultAzureCredential()
    container = BlobServiceClient(settings.blob_url, credential=cred).get_container_client("resumes")
    cu = ContentUnderstandingClient(settings.ai_endpoint, credential=cred)
    (OUT / "raw").mkdir(parents=True, exist_ok=True)

    blobs = sorted(b.name for b in container.list_blobs())
    if args.only:
        blobs = [b for b in blobs if Path(b).stem in set(args.only)]
    if args.limit:
        blobs = blobs[: args.limit]
    print(f"Extracting {len(blobs)} resumes with '{ANALYZER_ID}'...")

    def process(name: str) -> tuple[str, float]:
        start = time.time()
        data = container.download_blob(name).readall()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        result = cu.analyze_bytes(ANALYZER_ID, data, mime, name)
        cand_id = Path(name).stem
        (OUT / "raw" / f"{cand_id}.json").write_text(json.dumps(result, indent=2))
        profile = to_profile(cand_id, f"resumes/{name}", result)
        (OUT / f"{cand_id}.json").write_text(json.dumps(profile, indent=2))
        return name, time.time() - start

    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, n): n for n in blobs}
        for i, fut in enumerate(as_completed(futures), 1):
            name = futures[fut]
            try:
                _, secs = fut.result()
                print(f"  [{i:>2}/{len(blobs)}] {name:<16} {secs:5.1f}s")
            except Exception as exc:  # keep going; report at the end
                failures.append((name, str(exc)))
                print(f"  [{i:>2}/{len(blobs)}] {name:<16} FAILED: {str(exc)[:200]}")

    print(f"\nDone: {len(blobs) - len(failures)} succeeded, {len(failures)} failed -> {OUT}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
