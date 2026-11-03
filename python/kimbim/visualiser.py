# SPDX-License-Identifier: GPL-3.0-or-later
"""AI visualiser (D225): turn a sketch into a rendered image through an image model.

The model is external (like the online library catalogues, D216): the endpoint and key come from
the environment, never from the project file. ``KIMBIM_IMAGE_ENDPOINT`` is an OpenAI-compatible
``/images/edits`` URL (default ``https://api.openai.com/v1/images/edits``),
``KIMBIM_IMAGE_API_KEY`` the bearer token and ``KIMBIM_IMAGE_MODEL`` the model (default
``gpt-image-1``). The sketch (PNG/JPEG/WebP, up to 10 MB) is sent as multipart form data with the
prompt and size; the returned base64 image is written next to it (or to the chosen path). No key
or endpoint means a clear error, never a placeholder image.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import urllib.error
import urllib.request
import uuid

from . import app_bridge as B
from . import authoring as A

DEFAULT_ENDPOINT = "https://api.openai.com/v1/images/edits"
DEFAULT_MODEL = "gpt-image-1"
MAX_BYTES = 10 * 1024 * 1024
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
SIZES = ("1024x1024", "1024x1536", "1536x1024", "auto")


def _config() -> dict:
    return {
        "endpoint": os.environ.get("KIMBIM_IMAGE_ENDPOINT", DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT,
        "model": os.environ.get("KIMBIM_IMAGE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "key": os.environ.get("KIMBIM_IMAGE_API_KEY", "").strip(),
    }


def visualiser_config() -> str:
    """What the visualiser will call; the key itself is never returned."""
    config = _config()
    return B._dump({"ok": True, "endpoint": config["endpoint"], "model": config["model"],
                    "configured": bool(config["key"]), "sizes": list(SIZES)})


def _multipart(fields: dict, path: pathlib.Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                      f'{value}\r\n'.encode("utf-8"))
    content = CONTENT_TYPES[path.suffix.lower()]
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                  f'filename="{path.name}"\r\nContent-Type: {content}\r\n\r\n'.encode("utf-8"))
    chunks.append(path.read_bytes())
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def render_sketch(image_path: str, prompt: str, output_path: str = "", size: str = "1024x1024") -> str:
    """Send a sketch and a prompt to the image model and save the returned image."""
    if B._model is None:
        return A._fail("no model open")
    prompt = str(prompt or "").strip()
    if not prompt:
        return A._fail("describe the visualisation you want")
    if not isinstance(image_path, str) or not image_path.strip():
        return A._fail("choose a sketch image")
    source = pathlib.Path(image_path)
    if not source.is_file():
        return A._fail("the sketch image does not exist")
    if source.suffix.lower() not in SUFFIXES:
        return A._fail("the sketch is a PNG, JPEG or WebP image")
    if source.stat().st_size > MAX_BYTES:
        return A._fail("the sketch is larger than 10 MB")
    size = str(size or "1024x1024")
    if size not in SIZES:
        return A._fail(f"the size is one of {', '.join(SIZES)}")
    config = _config()
    if not config["key"]:
        return A._fail("no image model is configured: set KIMBIM_IMAGE_API_KEY (and optionally "
                       "KIMBIM_IMAGE_ENDPOINT / KIMBIM_IMAGE_MODEL)")
    body, boundary = _multipart({"model": config["model"], "prompt": prompt, "size": size,
                                 "response_format": "b64_json"}, source)
    request = urllib.request.Request(
        config["endpoint"], data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": f"Bearer {config['key']}"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:400]
        return A._fail(f"the image model returned HTTP {ex.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        return A._fail(f"could not reach the image model: {ex}")
    except (TypeError, ValueError) as ex:
        return A._fail(f"the image model returned bad JSON: {ex}")
    try:
        item = payload["data"][0]
        encoded = item.get("b64_json")
        if not encoded and item.get("url"):
            with urllib.request.urlopen(item["url"], timeout=180) as response:
                data = response.read()
        else:
            data = base64.b64decode(encoded or "")
    except (KeyError, IndexError, TypeError, ValueError) as ex:
        return A._fail(f"the image model returned no image: {ex}")
    if not data:
        return A._fail("the image model returned an empty image")
    target = pathlib.Path(output_path) if str(output_path or "").strip() else \
        source.with_name(f"{source.stem}-ai.png")
    if target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        target = target.with_suffix(".png")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as ex:
        return A._fail(f"could not write the image: {ex}")
    return B._dump({"ok": True, "path": str(target), "bytes": len(data), "model": config["model"],
                    "prompt": prompt})
