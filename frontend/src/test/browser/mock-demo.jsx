import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import App from '../../App';
import { AuthProvider } from '../../auth/AuthContext';
import api, { TOKEN_KEY } from '../../api/client';
import { createMockDemoApi, demoFixtures } from './mockApi';
import '../../styles.css';

// This HTML entry is never part of the production build. All state is in memory.
// Do not read or replace the user's real saved login token.
const values = new Map([[TOKEN_KEY, 'mock-memory-token']]);
const memoryStorage = {
  getItem: (key) => values.get(key) || null,
  setItem: (key, value) => values.set(key, value),
  removeItem: (key) => values.delete(key),
};

api.interceptors.request.clear();
api.interceptors.response.clear();

function MockDemo() {
  const parameters = new URLSearchParams(window.location.search);
  const role = parameters.get('role') === 'student' ? 'student' : 'coordinator';
  const scenario = ['empty', 'error'].includes(parameters.get('scenario')) ? parameters.get('scenario') : 'records';
  const mock = React.useMemo(() => createMockDemoApi({ role, scenario }), [role, scenario]);
  api.defaults.adapter = mock.adapter;
  const [callCount, setCallCount] = useState(null);
  const initial = parameters.get('path') || (role === 'student' ? '/student/dashboard' : '/coordinator/imports');

  function selectFixture(key) {
    const picker = document.getElementById('coordinator-csv');
    if (!picker || picker.disabled) return;
    const fixture = demoFixtures[key];
    const transfer = new DataTransfer();
    transfer.items.add(new File([fixture.text], fixture.name, { type: 'text/csv' }));
    picker.files = transfer.files;
    picker.dispatchEvent(new Event('change', { bubbles: true }));
  }

  return <>
    <aside aria-label="Mock verification controls" style={{ position: 'relative', zIndex: 40, background: '#f8e5b9',
      color: '#442d12', padding: '10px 15px', fontSize: 12, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
      <strong>MOCKED UI CHECK — no backend, database, or model calls</strong>
      <a href="/mock-demo.html">Coordinator CSV</a>
      <a href="/mock-demo.html?role=student">Student: zero score / missing forecast</a>
      <a href="/mock-demo.html?path=/coordinator/dashboard&amp;scenario=empty">Empty overview</a>
      <a href="/mock-demo.html?path=/coordinator/dashboard&amp;scenario=error">Error overview</a>
      {role === 'coordinator' && <>
        <button type="button" className="button button-secondary button-small" onClick={() => selectFixture('valid')}>Select existing valid fixture</button>
        <button type="button" className="button button-secondary button-small" onClick={() => selectFixture('rejections')}>Select existing rejection fixture</button>
      </>}
      <button type="button" className="button button-secondary button-small" onClick={() => setCallCount(mock.calls.length)}>Check mock request count</button>
      {callCount !== null && <span role="status">{callCount} requests handled in memory; no HTTP transport</span>}
    </aside>
    <MemoryRouter initialEntries={[initial]}>
      <AuthProvider tokenStorage={memoryStorage}><App /></AuthProvider>
    </MemoryRouter>
  </>;
}

ReactDOM.createRoot(document.getElementById('root')).render(<MockDemo />);
