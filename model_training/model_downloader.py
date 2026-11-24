"""Downloader utility for large model weights hosted on Google Drive."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

import requests

from config.settings import (
    HF_MODEL_CHECKPOINT_PATH,
    HF_MODEL_DIR,
    HF_MODEL_GDRIVE_FILE_ID,
    HF_MODEL_GDRIVE_URL,
)


def extract_gdrive_file_id(url_or_id: str) -> str:
    """Extract a Google Drive file ID from a full sharing URL or plain ID."""
    url_or_id = url_or_id.strip()
    # Match /file/d/<id>/
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
    # Match id=<id>
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id


def download_from_gdrive(
    file_id_or_url: str,
    target_path: Path | str,
    min_expected_bytes: int = 10 * 1024 * 1024,  # at least 10 MB
    force: bool = False,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> Path:
    """
    Download a large public file from Google Drive, handling the virus-scan warning.
    Writes to a temporary file first and renames atomically upon success.
    """
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not force:
        size = target.stat().st_size
        if size >= min_expected_bytes:
            print(f"[INFO] Model checkpoint already exists at {target} ({size / (1024 * 1024):.1f} MB). Skipping download.")
            return target
        else:
            print(f"[WARN] Existing model file is suspiciously small ({size} bytes). Re-downloading...")

    file_id = extract_gdrive_file_id(file_id_or_url)
    print(f"\n[INFO] Initiating download of model weights from Google Drive...")
    print(f"[INFO] Target path: {target}")
    print(f"[INFO] Google Drive File ID: {file_id}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    base_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = session.get(base_url, stream=True, timeout=30)
    response.raise_for_status()

    # Google Drive presents an HTML confirmation for files exceeding scanning limits (~100MB)
    if "text/html" in response.headers.get("Content-Type", ""):
        html = response.text
        action_match = re.search(r'action=["\']([^"\']+)["\']', html)
        action_url = action_match.group(1) if action_match else "https://drive.usercontent.google.com/download"

        inputs = dict(re.findall(r'<input[^>]+name=["\']([^"\']+)["\'][^>]+value=["\']([^"\']*)["\']', html))
        inputs2 = dict(re.findall(r'<input[^>]+value=["\']([^"\']*)["\'][^>]+name=["\']([^"\']+)["\']', html))
        inputs.update({k: v for v, k in inputs2.items()})

        if not inputs:
            confirm_match = re.search(r"confirm=([0-9A-Za-z_]+)", html)
            confirm_val = confirm_match.group(1) if confirm_match else "t"
            inputs = {"id": file_id, "export": "download", "confirm": confirm_val}

        response = session.get(action_url, params=inputs, stream=True, timeout=30)
        response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        snippet = response.text[:500]
        raise RuntimeError(
            f"Failed to obtain binary download from Google Drive. Received HTML response instead:\n{snippet}"
        )

    total_bytes_str = response.headers.get("Content-Length")
    total_bytes = int(total_bytes_str) if total_bytes_str and total_bytes_str.isdigit() else None

    if total_bytes:
        print(f"[INFO] Download size: {total_bytes / (1024 * 1024):.1f} MB")
    else:
        print("[INFO] Download size: unknown (streaming)")

    temp_path = target.with_suffix(f"{target.suffix}.tmp_{int(time.time())}")
    downloaded_bytes = 0
    chunk_size = 2 * 1024 * 1024  # 2MB chunks
    start_time = time.time()
    last_print_time = start_time

    try:
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded_bytes += len(chunk)
                    current_time = time.time()

                    if progress_callback:
                        progress_callback(downloaded_bytes, total_bytes)

                    # Print progress every 1.5 seconds or on finish
                    if current_time - last_print_time >= 1.5:
                        elapsed = current_time - start_time
                        speed_mbps = (downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                        if total_bytes:
                            percent = (downloaded_bytes / total_bytes) * 100
                            mb_down = downloaded_bytes / (1024 * 1024)
                            mb_total = total_bytes / (1024 * 1024)
                            print(
                                f"\r[DOWNLOADING] {mb_down:.1f} MB / {mb_total:.1f} MB ({percent:.1f}%) "
                                f"- Speed: {speed_mbps:.2f} MB/s",
                                end="",
                                flush=True,
                            )
                        else:
                            mb_down = downloaded_bytes / (1024 * 1024)
                            print(
                                f"\r[DOWNLOADING] {mb_down:.1f} MB downloaded - Speed: {speed_mbps:.2f} MB/s",
                                end="",
                                flush=True,
                            )
                        last_print_time = current_time

        elapsed_total = time.time() - start_time
        final_mb = downloaded_bytes / (1024 * 1024)
        print(f"\n[INFO] Download finished: {final_mb:.1f} MB in {elapsed_total:.1f}s")

        # Sanity check file size
        if downloaded_bytes < min_expected_bytes:
            raise ValueError(
                f"Downloaded file size ({downloaded_bytes} bytes) is less than expected minimum ({min_expected_bytes} bytes)."
            )

        # Atomic replace
        if target.exists():
            target.unlink()
        temp_path.rename(target)
        print(f"[SUCCESS] Model weights saved to {target}\n")
        return target

    except Exception as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise RuntimeError(f"Error while downloading model weights: {exc}") from exc


def ensure_hf_model_ready(force: bool = False) -> Path:
    """Ensure that the Hugging Face model checkpoint exists, downloading if necessary."""
    file_source = HF_MODEL_GDRIVE_URL or HF_MODEL_GDRIVE_FILE_ID
    return download_from_gdrive(
        file_id_or_url=file_source,
        target_path=HF_MODEL_CHECKPOINT_PATH,
        min_expected_bytes=50 * 1024 * 1024,  # Checkpoint is ~900 MB, expect at least 50 MB
        force=force,
    )
