"""Read one directory or a small text file from a job's recorded MLflow run."""

import json
import re
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.services.mlflow_failure_provider import mlflow_client_options, parse_run_reference

PREVIEW_LIMIT = 64 * 1024
DIRECTORY_LIMIT = 4 * 1024 * 1024


def valid_path(path: str) -> bool:
    if not path:
        return True
    return (
        len(path) <= 2048
        and not any(part in ("", ".", "..") for part in path.split("/"))
        and "\\" not in path
        and not re.search(r"[\x00-\x1f\x7f]", path)
        and unquote(path) == path
    )


def _origin(url: str):
    parsed = urlsplit(url)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username is not None):
        return None
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname, parsed.port or default_port


async def _read(run_url: str, path: str, *, preview: bool, page_token: str = "") -> bytes:
    if not settings.MLFLOW_TRACKING_URI:
        raise HTTPException(503, "MLflow tracking is not configured.")
    try:
        origin = _origin(run_url)
        configured = (settings.MLFLOW_TRACKING_URI, settings.MLFLOW_BASE_URL)
        trusted = {_origin(url) for url in configured if url}
        ref = parse_run_reference(run_url) if origin and origin in trusted else None
    except ValueError:
        ref = None
    if not ref:
        raise HTTPException(422, "This run link cannot be explored here. Open it in MLflow.")
    run_id, workspace, _ = ref
    if preview:
        endpoint = "/get-artifact"
        params = {"run_uuid": run_id, "path": path}
        limit = PREVIEW_LIMIT
        too_large = "This file exceeds the 64 KiB preview limit."
    else:
        endpoint = "/api/2.0/mlflow/artifacts/list"
        params = {"run_id": run_id, "path": path}
        if page_token:
            params["page_token"] = page_token
        limit = DIRECTORY_LIMIT
        too_large = "MLflow returned an oversized directory page."
    try:
        async with httpx.AsyncClient(**mlflow_client_options(workspace)) as client:
            async with client.stream("GET", endpoint, params=params, headers={"Accept-Encoding": "identity"}) as response:
                if response.status_code == 404:
                    raise HTTPException(404, "MLflow could not find this run or artifact.")
                if response.status_code in (401, 403):
                    raise HTTPException(403, "The Control Center MLflow connection cannot read this run.")
                if response.status_code != 200:
                    raise HTTPException(502, "MLflow could not complete the request.")
                size = response.headers.get("content-length", "")
                if size.isdecimal() and int(size) > limit:
                    raise HTTPException(413, too_large)
                content = bytearray()
                async for chunk in response.aiter_bytes(16384):
                    if len(content) + len(chunk) > limit:
                        raise HTTPException(413, too_large)
                    content.extend(chunk)
                return bytes(content)
    except httpx.TimeoutException:
        raise HTTPException(504, "MLflow timed out. Try again.") from None
    except httpx.RequestError:
        raise HTTPException(502, "MLflow is unavailable. Try again.") from None


async def list_directory(run_url: str, path: str, page_token: str) -> dict:
    if not valid_path(path):
        raise HTTPException(422, "Invalid artifact folder.")
    raw = await _read(run_url, path, preview=False, page_token=page_token)
    try:
        page = json.loads(raw)
        files = page.get("files", [])
        if not isinstance(files, list):
            raise ValueError
        entries = []
        for item in files:
            child = item["path"]
            if not child or not valid_path(child) or child.rpartition("/")[0] != path:
                continue
            entries.append({"path": child, "is_dir": item.get("is_dir", False), "file_size": item.get("file_size")})
        return {"files": entries, "next_page_token": page.get("next_page_token") or None}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(502, "Invalid directory listing from MLflow.") from None


async def preview_file(run_url: str, path: str) -> dict:
    if not path or not valid_path(path):
        raise HTTPException(422, "Invalid artifact file.")
    raw = await _read(run_url, path, preview=True)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(415, "Preview is available for UTF-8 text files only.") from None
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        raise HTTPException(415, "Preview is available for text files only.")
    return {"text": text}
