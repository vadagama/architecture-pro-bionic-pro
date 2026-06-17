import React from 'react';
import ReportPage from './components/ReportPage';

// Фронт больше не интегрируется с Keycloak напрямую и не работает с токенами.
// Вся авторизация идёт через bionicpro-auth (BFF) по сессионной cookie.
const App: React.FC = () => {
  return (
    <div className="App">
      <ReportPage />
    </div>
  );
};

export default App;
