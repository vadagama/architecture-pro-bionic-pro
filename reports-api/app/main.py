"""reports-api — бэкенд отчётности BionicPRO (Задания 2–4).

Отдаёт отчёт о работе протеза из OLAP-витрины ClickHouse. Ограничение доступа:
отчёт выдаётся ТОЛЬКО по самому пользователю — username/sub берутся из
проверенного access_token, параметра "чужой пользователь" в API нет.

Задание 3 (снижение нагрузки на OLAP): cache-aside через S3 + CDN. На запрос
сервис делает лёгкий probe версии данных; если отчёт этой версии уже лежит в S3,
возвращает только ссылку на CDN (без выгрузки из OLAP). Иначе — выгружает отчёт
один раз, кладёт в S3 и отдаёт ссылку. Сами строки браузер берёт из CDN.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Query

from . import clickhouse, s3
from .auth import CurrentUser, get_current_user

app = FastAPI(title="reports-api", version="1.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "clickhouse": clickhouse.ping()}


def _build_full_report(username: str, date_from: Optional[str], date_to: Optional[str]) -> dict:
    """Полная выгрузка отчёта из OLAP (тяжёлый путь, только при cache miss)."""
    rows = clickhouse.fetch_user_report(
        username=username, date_from=date_from, date_to=date_to
    )
    for r in rows:
        if isinstance(r.get("report_date"), date):
            r["report_date"] = r["report_date"].isoformat()
    return {
        "username": username,
        "report_type": "prosthesis_usage",
        "periods_count": len(rows),
        "rows": rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/reports")
def get_reports(
    user: CurrentUser = Depends(get_current_user),
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
) -> dict:
    """Отчёт текущего пользователя через cache-aside (S3 + CDN).

    Доступ только к собственным данным: фильтр по user.username из токена.
    Период ограничен тем, что уже обработано ETL/CDC (есть в витрине).
    """
    df = date_from.isoformat() if date_from else None
    dt = date_to.isoformat() if date_to else None

    base = {"username": user.username, "report_type": "prosthesis_usage"}

    # 1. Лёгкий probe версии — без выгрузки строк.
    meta = clickhouse.fetch_report_meta(user.username, date_from=df, date_to=dt)
    if meta is None:
        return {
            **base,
            "periods_count": 0,
            "report_url": None,
            "note": (
                "Данных нет: период ещё не обработан ETL/CDC для этого пользователя."
            ),
        }

    # 2. Иммутабельный ключ объекта по версии данных (+ диапазону дат).
    version = f"{meta['version']}:{df or ''}:{dt or ''}"
    key = s3.report_key(user.sub, version)

    try:
        cached = s3.object_exists(key)
        if not cached:
            # 3. Cache miss: единственная тяжёлая выгрузка из OLAP → кладём в S3.
            s3.put_report(key, _build_full_report(user.username, df, dt))
        report_url = s3.build_cdn_url(key)
        return {
            **base,
            "periods_count": meta["periods"],
            "report_url": report_url,
            "cached": cached,
            "note": (
                "Отчёт раздаётся через CDN; OLAP не запрашивается повторно "
                "для уже сформированной версии."
            ),
        }
    except Exception as exc:  # noqa: BLE001 — S3/CDN недоступны: graceful fallback
        # Возвращаем строки inline, чтобы функция отчёта оставалась доступной.
        report = _build_full_report(user.username, df, dt)
        report["report_url"] = None
        report["note"] = f"S3/CDN недоступны ({exc}); отчёт отдан напрямую из OLAP."
        return report
