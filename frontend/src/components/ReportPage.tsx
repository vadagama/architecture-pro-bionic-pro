import React, { useEffect, useState } from 'react';

// URL бэкенда авторизации (bionicpro-auth / BFF).
const AUTH_URL = process.env.REACT_APP_AUTH_URL || 'http://localhost:8000';

interface SessionState {
  authenticated: boolean;
  username?: string;
  roles?: string[];
}

const ReportPage: React.FC = () => {
  const [session, setSession] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<string | null>(null);
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
      // Запрос идёт на BFF с сессионной cookie; токен подставляет сам BFF.
      const response = await fetch(`${AUTH_URL}/api/reports`, { credentials: 'include' });
      if (response.status === 401) {
        setSession({ authenticated: false });
        setError('Session expired, please login again');
        return;
      }
      const data = await response.json();
      setReport(JSON.stringify(data.report ?? data, null, 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
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

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <div className="p-8 bg-white rounded-lg shadow-md">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl font-bold">Usage Reports</h1>
          <button onClick={logout} className="text-sm text-gray-500 hover:text-gray-800">
            Logout ({session.username})
          </button>
        </div>

        <button
          onClick={downloadReport}
          disabled={loading}
          className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
            loading ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {loading ? 'Generating Report...' : 'Download Report'}
        </button>

        {report && (
          <pre className="mt-4 p-4 bg-gray-50 text-gray-800 rounded text-xs overflow-auto max-w-md">
            {report}
          </pre>
        )}

        {error && (
          <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">{error}</div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;
