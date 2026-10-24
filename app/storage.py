"""File uploads in a private Supabase Storage bucket (local disk under UPLOAD_DIR in tests).

The server uploads with the service-role key, and downloads go through short-lived signed URLs,
so the bucket never needs to be public.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
import uuid
from urllib.parse import quote

import certifi
from flask import current_app, redirect, send_from_directory
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

# certifi's CA bundle: python.org macOS builds ship without system certificates.
_SSL = ssl.create_default_context(cafile=certifi.where())


def _storage_request(path: str, data: bytes, content_type: str) -> dict:
    cfg = current_app.config
    if not (cfg["SUPABASE_URL"] and cfg["SUPABASE_SERVICE_ROLE_KEY"]):
        raise RuntimeError("Uploads need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env")
    key = cfg["SUPABASE_SERVICE_ROLE_KEY"]
    req = urllib.request.Request(
        f"{cfg['SUPABASE_URL'].rstrip('/')}/storage/v1/{path}", data=data, method="POST",
        headers={"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=30, context=_SSL) as resp:
        return json.loads(resp.read() or b"{}")


def _object_path(key: str) -> str:
    return f"{current_app.config['SUPABASE_STORAGE_BUCKET']}/{quote(key)}"


def save(file: FileStorage, prefix: str) -> str:
    key = f"{prefix}/{uuid.uuid4().hex}-{secure_filename(file.filename or 'upload')}"
    if current_app.testing:
        path = os.path.join(current_app.config["UPLOAD_DIR"], key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file.save(path)
    else:
        _storage_request(f"object/{_object_path(key)}", file.stream.read(),
                         file.mimetype or "application/octet-stream")
    return key


def serve(key: str, download_name: str):
    """Response that delivers the file: a 5-minute signed URL, or from disk in tests."""
    if current_app.testing:
        return send_from_directory(current_app.config["UPLOAD_DIR"], key, as_attachment=True,
                                   download_name=download_name)
    signed = _storage_request(f"object/sign/{_object_path(key)}",
                              json.dumps({"expiresIn": 300}).encode(), "application/json")
    base = current_app.config["SUPABASE_URL"].rstrip("/")
    return redirect(f"{base}/storage/v1{signed['signedURL']}&download={quote(download_name)}")
