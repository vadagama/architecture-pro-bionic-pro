"""Кэш готовых отчётов в объектном хранилище S3 (Minio) и раздача через CDN.

Задание 3. Чтобы не нагружать OLAP повторными запросами одного и того же
отчёта, сформированный отчёт кладётся в S3 один раз, а браузер забирает его
напрямую через CDN (Nginx). reports-api лишь выдаёт ссылку.

Защита объектов (capability-URL): bucket разрешает анонимное скачивание, но имя
объекта неугадываемо — сегмент ключа = HMAC_SHA256(secret, sub:version). Ссылку
выдаёт только API после проверки JWT, а угадать чужой ключ нельзя. Версия в
HMAC делает ключ иммутабельным: новые данные → новая версия → новый ключ →
свежий объект в CDN (инвалидация через смену ключа, а не TTL).
"""
import hashlib
import hmac
import json
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .config import get_settings

settings = get_settings()


@lru_cache
def _client():
    # path-style addressing + s3v4 — обязательны для Minio.
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def report_key(sub: str, version: str) -> str:
    """Неугадываемый ключ объекта: <sub>/<hmac32>.json.

    version кодирует data_version (+ диапазон дат), поэтому объект иммутабелен.
    """
    material = f"{sub}:{version}".encode("utf-8")
    digest = hmac.new(
        settings.report_url_secret.encode("utf-8"), material, hashlib.sha256
    ).hexdigest()[:32]
    return f"{sub}/{digest}.json"


def object_exists(key: str) -> bool:
    """Есть ли уже сформированный отчёт в S3 (cache hit)."""
    try:
        _client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def put_report(key: str, payload: dict) -> None:
    """Положить готовый отчёт (JSON) в S3."""
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


def build_cdn_url(key: str) -> str:
    """Публичная ссылка на отчёт через CDN (Nginx reverse-proxy перед Minio)."""
    return f"{settings.cdn_public_base_url}/{settings.s3_bucket}/{key}"
