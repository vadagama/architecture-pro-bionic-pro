"""reports-api — бэкенд отчётности BionicPRO (Задание 2).

Отдаёт готовый отчёт о работе протеза из OLAP-витрины ClickHouse, которую
наполняет Airflow DAG. Ограничение доступа: отчёт выдаётся ТОЛЬКО по самому
пользователю — username берётся из проверенного access_token, параметра
"чужой пользователь" в API нет.
"""
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, Query

from . import clickhouse
from .auth import CurrentUser, get_current_user

app = FastAPI(title="reports-api", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "clickhouse": clickhouse.ping()}


@app.get("/reports")
def get_reports(
    user: CurrentUser = Depends(get_current_user),
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
) -> dict:
    """Отчёт по работе протеза текущего пользователя.

    Доступ только к собственным данным: фильтр по user.username из токена.
    Период ограничен тем, что уже обработано Airflow (есть в витрине).
    """
    rows = clickhouse.fetch_user_report(
        username=user.username,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )

    # Сериализуем date → ISO для JSON.
    for r in rows:
        if isinstance(r.get("report_date"), date):
            r["report_date"] = r["report_date"].isoformat()

    return {
        "username": user.username,
        "report_type": "prosthesis_usage",
        "periods_count": len(rows),
        "rows": rows,
        "note": (
            "Доступны только периоды, обработанные ETL (Airflow). "
            "Если данных нет — отчёт ещё не сформирован для этого пользователя."
        ),
    }
