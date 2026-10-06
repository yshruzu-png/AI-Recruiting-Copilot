"""Settings loaded from .env (written by scripts/write_env.sh from Terraform outputs)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    storage_account: str = os.getenv("AZURE_STORAGE_ACCOUNT", "")
    ai_endpoint: str = os.getenv("AZURE_AI_ENDPOINT", "").rstrip("/")
    search_endpoint: str = os.getenv("AZURE_SEARCH_ENDPOINT", "")
    chat_deployment: str = os.getenv("AZURE_CHAT_DEPLOYMENT", "gpt-4.1-mini")
    embedding_deployment: str = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")

    @property
    def blob_url(self) -> str:
        return f"https://{self.storage_account}.blob.core.windows.net"


settings = Settings()
