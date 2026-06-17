import React, { useEffect, useState } from 'react';

// URL бэкенда авторизации (bionicpro-auth / BFF).
const AUTH_URL = process.env.REACT_APP_AUTH_URL || 'http://localhost:8000';

interface SessionState {
  authenticated: boolean;
  username?: string;
  roles?: string[];
}

// Строка витрины отчётности (приходит из reports-api через BFF).
interface ReportRow {
  report_date: string;
  full_name: string;
  country: string;
  prosthesis_model: string;
  serial_number: string;
  total_sessions: number;
  total_active_min: number;
  avg_response_ms: number;
  max_response_ms: number;
  avg_signal_quality: number;
  total_movements: number;
  avg_battery_pct: number;
}

interface Report {
  username: string;
  report_type: string;
  periods_count: number;
  rows?: ReportRow[];
  note?: string;
  // Задание 3: BFF/reports-api может вернуть ссылку на отчёт в CDN вместо строк.
  report_url?: string | null;
  cached?: boolean;
}

const ReportPage: React.FC = () => {
  const [session, setSession] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Проверяем статус сессии у BFF. Никаких токенов на клиенте нет —
  // авторизация определяется по HTTP-only cookie, которую браузер шлёт сам.
  useEffect(() => {
    fetch(`${AUTH_URL}/auth/me`, { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : { authenticated: false }))
      .then((data) => setSession(data))
      .catch(() => setSession({ authenticated: false }));
  }, []);

  const login = () => {
    // Редирект на BFF, который запускает Authorization Code + PKCE.
    window.location.href = `${AUTH_URL}/auth/login`;
  };

  const logout = async () => {
    await fetch(`${AUTH_URL}/auth/logout`, { method: 'POST', credentials: 'include' });
    setSession({ authenticated: false });
    setReport(null);
  };

  const downloadReport = async () => {
    try {
      setLoading(true);
      setError(null);
      setReport(null);
      // Запрос идёт на BFF с сессионной cookie; токен подставляет сам BFF,
      // а reports-api отдаёт отчёт ТОЛЬКО по текущему пользователю.
      const response = await fetch(`${AUTH_URL}/api/reports`, { credentials: 'include' });
      if (response.status === 401) {
        setSession({ authenticated: false });
        setError('Сессия истекла, войдите снова');
        return;
      }
      const data = await response.json();
      const payload: Report & { error?: string } = data.report ?? data;
      // reports-api недоступен / ошибка апстрима — это не "нет данных".
      if (!response.ok || payload?.error) {
        setError(payload?.error ? `Сервис отчётов: ${payload.error}` : 'Не удалось получить отчёт');
        return;
      }
      // Задание 3: если отчёт лежит в S3, BFF вернёт ссылку на CDN — данные
      // забираем напрямую из CDN (без credentials), разгружая API и OLAP.
      if (payload.report_url) {
        const cdnRes = await fetch(payload.report_url);
        if (!cdnRes.ok) {
          setError('Не удалось загрузить отчёт из CDN');
          return;
        }
        const cdnData: Report = await cdnRes.json();
        setReport(cdnData);
        return;
      }
      // Иначе — строки пришли inline (нет данных или S3/CDN недоступны).
      setReport(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Произошла ошибка');
    } finally {
      setLoading(false);
    }
  };

  if (session === null) {
    return <div>Loading...</div>;
  }

  if (!session.authenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <button
          onClick={login}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Login
        </button>
      </div>
    );
  }

  const hasRows = report && report.rows && report.rows.length > 0;

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 py-8">
      <div className="p-8 bg-white rounded-lg shadow-md max-w-4xl w-full">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl font-bold">Отчёт о работе протеза</h1>
          <button onClick={logout} className="text-sm text-gray-500 hover:text-gray-800">
            Выйти ({session.username})
          </button>
        </div>

        <button
          onClick={downloadReport}
          disabled={loading}
          className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
            loading ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {loading ? 'Формируем отчёт...' : 'Получить отчёт'}
        </button>

        {report && !hasRows && (
          <div className="mt-4 p-4 bg-yellow-50 text-yellow-800 rounded">
            Данные отчёта ещё не сформированы ETL-процессом (Airflow) для пользователя{' '}
            <b>{report.username}</b>. Попробуйте позже.
          </div>
        )}

        {hasRows && (
          <div className="mt-6 overflow-auto">
            <p className="mb-2 text-sm text-gray-600">
              Пользователь: <b>{report.username}</b> · периодов: {report.periods_count}
            </p>
            <table className="min-w-full text-sm border border-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">Дата</th>
                  <th className="px-3 py-2 text-left">Модель</th>
                  <th className="px-3 py-2 text-right">Сессий</th>
                  <th className="px-3 py-2 text-right">Активность, мин</th>
                  <th className="px-3 py-2 text-right">Откл., мс (ср/макс)</th>
                  <th className="px-3 py-2 text-right">Качество сигнала</th>
                  <th className="px-3 py-2 text-right">Движений</th>
                  <th className="px-3 py-2 text-right">Батарея, %</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((r) => (
                  <tr key={r.report_date} className="border-t border-gray-100">
                    <td className="px-3 py-2">{r.report_date}</td>
                    <td className="px-3 py-2">{r.prosthesis_model}</td>
                    <td className="px-3 py-2 text-right">{r.total_sessions}</td>
                    <td className="px-3 py-2 text-right">{r.total_active_min}</td>
                    <td className="px-3 py-2 text-right">
                      {r.avg_response_ms} / {r.max_response_ms}
                    </td>
                    <td className="px-3 py-2 text-right">{r.avg_signal_quality}</td>
                    <td className="px-3 py-2 text-right">{r.total_movements}</td>
                    <td className="px-3 py-2 text-right">{r.avg_battery_pct}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {error && (
          <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">{error}</div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;
