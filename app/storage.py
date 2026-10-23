"""File uploads: S3 when S3_BUCKET is set, otherwise local disk under UPLOAD_DIR."""

from __future__ import annotations

import os
import uuid

from flask import current_app, redirect, send_from_directory
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


def _s3():
    import boto3

    return boto3.client("s3", region_name=current_app.config["AWS_REGION"])


def save(file: FileStorage, prefix: str) -> str:
    key = f"{prefix}/{uuid.uuid4().hex}-{secure_filename(file.filename or 'upload')}"
    bucket = current_app.config["S3_BUCKET"]
    if bucket:
        _s3().upload_fileobj(file.stream, bucket, key, ExtraArgs={"ContentType": file.mimetype})
    else:
        path = os.path.join(current_app.config["UPLOAD_DIR"], key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file.save(path)
    return key


def serve(key: str, download_name: str):
    """Response that delivers the file: a short-lived presigned URL on S3, else from disk."""
    bucket = current_app.config["S3_BUCKET"]
    if bucket:
        url = _s3().generate_presigned_url(
            "get_object", ExpiresIn=300,
            Params={"Bucket": bucket, "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{download_name}"'})
        return redirect(url)
    return send_from_directory(current_app.config["UPLOAD_DIR"], key, as_attachment=True,
                               download_name=download_name)
