"""GitHub App transport with fixed origins and bounded, inspectable requests."""

import base64
import hashlib
import hmac
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx
import jwt

from services.analysis.repository import EXCLUDED, EXTENSIONS, parse_sources


class GitHubError(ValueError):
    pass


def repository_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", value) or ".." in value:
        raise GitHubError("Invalid GitHub repository name")
    return value


def verify_webhook(body: bytes, signature: str, secret: str) -> bool:
    if not secret or len(body) > 1_000_000 or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@dataclass(frozen=True)
class AppConfig:
    app_id: str
    private_key: str

    @classmethod
    def from_env(cls):
        app_id = os.environ.get("SPECGUARD_GITHUB_APP_ID", "")
        key_path = os.environ.get("SPECGUARD_GITHUB_PRIVATE_KEY_FILE", "")
        if not app_id or not key_path:
            raise GitHubError("Configure the GitHub App ID and private key file")
        return cls(app_id, Path(key_path).read_text(encoding="utf-8"))

    def token(self, installation_id: int, transport=None) -> str:
        if installation_id < 1:
            raise GitHubError("Invalid installation")
        now = int(time.time())
        signed = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )
        client = GitHubClient(signed, transport=transport)
        return client.request("POST", f"/app/installations/{installation_id}/access_tokens")[
            "token"
        ]


class GitHubClient:
    def __init__(self, token: str, *, transport=None):
        self.token = token
        self.transport = transport

    def request(self, method: str, path: str, *, params=None, payload=None):
        if not path.startswith("/") or path.startswith("//") or ".." in path or "\\" in path:
            raise GitHubError("Invalid GitHub API path")
        with httpx.Client(
            base_url="https://api.github.com",
            timeout=20,
            follow_redirects=False,
            transport=self.transport,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        ) as client:
            try:
                with client.stream(method, path, params=params, json=payload) as response:
                    if response.status_code in (403, 429):
                        raise GitHubError("GitHub denied the request or its rate limit was reached")
                    if response.status_code in (401, 404):
                        raise GitHubError("GitHub resource unavailable for this installation")
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 8_000_000:
                            raise GitHubError("GitHub response exceeds size budget")
                    import json

                    return json.loads(content)
            except httpx.HTTPError as error:
                raise GitHubError(
                    "GitHub request failed; retry after checking the installation"
                ) from error

    def pages(self, path: str, *, key: str | None = None, max_pages: int = 10, params=None) -> list:
        result = []
        for page in range(1, max_pages + 1):
            payload = self.request(
                "GET", path, params={**(params or {}), "per_page": 100, "page": page}
            )
            values = payload[key] if key else payload
            if not isinstance(values, list):
                raise GitHubError("Unexpected GitHub collection response")
            result.extend(values)
            if len(values) < 100:
                return result
        raise GitHubError("GitHub collection exceeds pagination budget")

    def repositories(self) -> list[dict]:
        return self.pages("/installation/repositories", key="repositories")

    def assert_repository(self, repository: str):
        repository_name(repository)
        if repository.lower() not in {r["full_name"].lower() for r in self.repositories()}:
            raise GitHubError("Repository not authorized for this installation")

    def pulls(self, repository: str) -> list[dict]:
        self.assert_repository(repository)
        return self.pages(f"/repos/{repository}/pulls", params={"state": "open"})

    def issue(self, repository: str, number: int) -> dict:
        self.assert_repository(repository)
        if number < 1:
            raise GitHubError("Invalid issue number")
        return self.request("GET", f"/repos/{repository}/issues/{number}")

    def snapshot(self, repository: str, number: int) -> tuple[dict, dict]:
        self.assert_repository(repository)
        if number < 1:
            raise GitHubError("Invalid pull request number")
        pull = self.request("GET", f"/repos/{repository}/pulls/{number}")
        base, head = pull["base"]["sha"], pull["head"]["sha"]
        if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
            raise GitHubError("Invalid pull request revisions")
        changed = self.pages(f"/repos/{repository}/pulls/{number}/files")
        tree = self.request("GET", f"/repos/{repository}/git/trees/{head}", params={"recursive": 1})
        if tree.get("truncated"):
            raise GitHubError("Repository tree is truncated; use a smaller local checkout")
        changed_paths = {item["filename"] for item in changed}
        entries = sorted(tree["tree"], key=lambda e: (e["path"] not in changed_paths, e["path"]))
        files: list[dict[str, str]] = []
        excluded: list[dict[str, str]] = []
        total = 0
        started = time.monotonic()
        for entry in entries:
            path = entry["path"]
            parts = PurePosixPath(path)
            if parts.suffix not in EXTENSIONS:
                continue
            reason = ""
            if parts.is_absolute() or ".." in parts.parts or "\\" in path or ":" in path:
                reason = "Unsafe source path"
            elif entry.get("mode") not in ("100644", "100755") or entry.get("type") != "blob":
                reason = "Not a regular source file"
            elif EXCLUDED.intersection(parts.parts) or path.endswith(".d.ts") or ".min." in path:
                reason = "Generated or excluded source"
            elif (
                entry.get("size", 100001) > 100000
                or total + entry.get("size", 0) > 2000000
                or len(files) >= 200
                or time.monotonic() - started > 45
            ):
                reason = "Source budget exceeded"
            if reason:
                excluded.append({"path": path, "reason": reason})
                continue
            blob = self.request("GET", f"/repos/{repository}/git/blobs/{entry['sha']}")
            if blob.get("encoding") != "base64":
                excluded.append({"path": path, "reason": "Unsupported blob encoding"})
                continue
            try:
                raw = base64.b64decode(blob["content"], validate=False)
                if len(raw) > 100000:
                    raise ValueError("Source too large")
                source = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                excluded.append({"path": path, "reason": "Invalid or oversized UTF-8 source"})
                continue
            total += len(raw)
            files.append({"path": path, "source": source})
        index = parse_sources(files, base, head, changed_paths, excluded)
        return index, pull

    def publish(self, repository: str, number: int, run_id: str, report: str) -> str:
        self.assert_repository(repository)
        if number < 1 or not re.fullmatch(r"[0-9a-f]{24}", run_id) or len(report) > 60000:
            raise GitHubError("Invalid publication request")
        marker = f"<!-- specguard-run:{run_id} -->"
        for comment in self.pages(f"/repos/{repository}/issues/{number}/comments"):
            if marker in comment.get("body", "") and comment.get("user", {}).get("type") == "Bot":
                return comment["html_url"]
        result = self.request(
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            payload={"body": f"{report}\n\n{marker}"},
        )
        return result["html_url"]


def source_url(repository: str, revision: str, path: str, start: int, end: int) -> str:
    return f"https://github.com/{repository_name(repository)}/blob/{revision}/{quote(path, safe='/')}#L{start}-L{end}"
