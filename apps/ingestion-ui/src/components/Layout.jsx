import { NavLink, Outlet, useLocation } from 'react-router-dom';
import WorkspaceSelector from './WorkspaceSelector';

const nav = [
  { to: '/', label: 'Dashboard' },
  { to: '/ingest', label: 'Ingest' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/documents', label: 'Documents' },
  { to: '/graph', label: 'Graph' },
  { to: '/query', label: 'Query' },
];

export default function Layout() {
  const isDashboard = useLocation().pathname === '/';
  return (
    <div className="flex h-screen bg-gray-50 text-gray-900">
      <aside className="w-56 bg-gray-900 text-gray-100 flex flex-col shrink-0">
        <div className="px-4 py-5 text-lg font-bold tracking-tight border-b border-gray-700">
          GraphRAG
        </div>
        <nav className="flex-1 p-2 space-y-0.5">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm ${
                  isActive ? 'bg-gray-700 text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex-1 flex flex-col overflow-hidden">
        {!isDashboard && (
          <header className="flex items-center gap-3 px-6 py-3 border-b bg-white shrink-0">
            <WorkspaceSelector />
          </header>
        )}
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
