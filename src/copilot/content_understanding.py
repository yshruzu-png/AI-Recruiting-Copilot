"""
Minimal Azure Content Understanding REST client (API 2025-11-01) using Entra ID, no API keys.

Docs: https://learn.microsoft.com/rest/api/contentunderstanding/
"""
from __future__ import annotations

import base64
import time
from typing import Any

import requests
from azure.identity import DefaultAzureCredential

API_VERSION = "2025-11-01"
SCOPE = "https://cognitiveservices.azure.com/.default"


class ContentUnderstandingError(RuntimeError):
    pass


class ContentUnderstandingClient:
    def __init__(self, endpoint: str, credential: DefaultAzureCredential | None = None, timeout: int = 60):
        if not endpoint:
            raise ValueError("AZURE_AI_ENDPOINT is empty. Run ./scripts/write_env.sh first.")
        self.endpoint = endpoint.rstrip("/")
        self.credential = credential or DefaultAzureCredential()
        self.timeout = timeout
        self._token = None

    # -- plumbing -------------------------------------------------------------
    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        # refresh the token a few minutes before it expires
        if self._token is None or self._token.expires_on - time.time() < 300:
            self._token = self.credential.get_token(SCOPE)
        return {"Authorization": f"Bearer {self._token.token}", "Content-Type": content_type}

    def _url(self, path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"{self.endpoint}/contentunderstanding/{path}{sep}api-version={API_VERSION}"

    @staticmethod
    def _check(resp: requests.Response) -> requests.Response:
        if resp.status_code >= 400:
            raise ContentUnderstandingError(f"{resp.status_code} {resp.reason}: {resp.text[:1500]}")
        return resp

    def _poll(self, operation_url: str, interval: float = 2.0, max_wait: int = 600) -> dict[str, Any]:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            body = self._check(requests.get(operation_url, headers=self._headers(), timeout=self.timeout)).json()
            status = body.get("status", "").lower()
            if status == "succeeded":
                return body
            if status in ("failed", "canceled", "cancelled"):
                raise ContentUnderstandingError(f"Operation {status}: {body.get('error', body)}")
            time.sleep(interval)
        raise ContentUnderstandingError(f"Timed out after {max_wait}s waiting for {operation_url}")

    # -- resource defaults ----------------------------------------------------
    def get_defaults(self) -> dict[str, Any]:
        return self._check(requests.get(self._url("defaults"), headers=self._headers(), timeout=self.timeout)).json()

    def set_default_deployments(self, mapping: dict[str, str]) -> dict[str, Any]:
        """Map model names (e.g. 'gpt-4.1-mini') to your deployment names. One-time setup per resource."""
        resp = requests.patch(self._url("defaults"), json={"modelDeployments": mapping},
                              headers=self._headers("application/merge-patch+json"), timeout=self.timeout)
        return self._check(resp).json()

    # -- analyzers ------------------------------------------------------------
    def create_analyzer(self, analyzer_id: str, definition: dict[str, Any]) -> dict[str, Any]:
        resp = requests.put(self._url(f"analyzers/{analyzer_id}?allowReplace=true"), json=definition,
                            headers=self._headers(), timeout=self.timeout)
        self._check(resp)
        op = resp.headers.get("Operation-Location")
        return self._poll(op) if op else resp.json()

    def get_analyzer(self, analyzer_id: str) -> dict[str, Any]:
        return self._check(requests.get(self._url(f"analyzers/{analyzer_id}"), headers=self._headers(),
                                        timeout=self.timeout)).json()

    def analyze_bytes(self, analyzer_id: str, data: bytes, mime_type: str, name: str = "document") -> dict[str, Any]:
        """Send a file as base64 (works with keyless storage: no SAS URLs needed)."""
        body = {"inputs": [{"data": base64.b64encode(data).decode(), "mimeType": mime_type, "name": name}]}
        resp = requests.post(self._url(f"analyzers/{analyzer_id}:analyze"), json=body,
                             headers=self._headers(), timeout=self.timeout)
        self._check(resp)
        op = resp.headers.get("Operation-Location")
        if not op:
            raise ContentUnderstandingError("No Operation-Location header in analyze response")
        result = self._poll(op)
        return result.get("result", result)
