"""
Upload the synthetic dataset to Blob Storage using your Entra ID login (no keys).

Prereqs: az login, terraform apply, ./scripts/write_env.sh
Usage:   python scripts/upload_data.py
"""
import mimetypes
import os
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "synthetic"
mimetypes.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")
mimetypes.add_type("text/markdown", ".md")


def main() -> None:
    load_dotenv(ROOT / ".env")
    account = os.environ["AZURE_STORAGE_ACCOUNT"]
    service = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=DefaultAzureCredential())

    total = 0
    for container in ("resumes", "job-descriptions"):
        client = service.get_container_client(container)
        for f in sorted((DATA / container).iterdir()):
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            with f.open("rb") as fh:
                client.upload_blob(f.name, fh, overwrite=True, content_settings=ContentSettings(content_type=ctype))
            total += 1
            print(f"  {container}/{f.name}")
    print(f"Uploaded {total} files to {account}")


if __name__ == "__main__":
    main()
