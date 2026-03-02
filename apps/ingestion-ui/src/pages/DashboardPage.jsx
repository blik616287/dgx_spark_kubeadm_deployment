import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWorkspaces } from '../hooks/useWorkspaces';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { deleteWorkspace } from '../api';
import JobStatusBadge from '../components/JobStatusBadge';

export default function DashboardPage() {
  const { workspaces, loading, error, refresh } = useWorkspaces();
  const { workspace: activeWorkspace, switchWorkspace } = useWorkspace();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(null);

  const handleClick = (name) => {
    switchWorkspace(name);
    navigate('/ingest');
  };

  const handleDelete = async (e, name) => {
    e.stopPropagation();
    const action = name === 'default' ? 'Clear' : 'Delete';
    if (!confirm(`${action} workspace "${name}"? This removes all documents, entities, relationships, and embeddings. This cannot be undone.`)) return;
    try {
      setDeleting(name);
      await deleteWorkspace(name);
      if (activeWorkspace === name && name !== 'default') {
        switchWorkspace('default');
      }
      refresh();
    } catch (err) {
      alert(`Failed to delete workspace: ${err.message}`);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Workspaces</h1>
        <button onClick={refresh} className="text-sm text-blue-600 hover:underline">
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm mb-4">{error}</div>
      )}

      {loading && !workspaces.length ? (
        <p className="text-gray-400">Loading...</p>
      ) : workspaces.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg">No workspaces yet</p>
          <p className="text-sm mt-1">Select a workspace and upload documents to get started.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {workspaces.map((ws) => (
            <div
              key={ws.name}
              onClick={() => handleClick(ws.name)}
              className="bg-white border rounded-lg p-5 hover:shadow-md transition-shadow cursor-pointer"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold text-lg">{ws.name}</h3>
                <button
                  onClick={(e) => handleDelete(e, ws.name)}
                  disabled={deleting === ws.name}
                  className="text-xs text-red-500 hover:text-red-700 disabled:opacity-50"
                  title={ws.name === 'default' ? 'Clear workspace' : 'Delete workspace'}
                >
                  {deleting === ws.name ? 'Deleting...' : ws.name === 'default' ? 'Clear' : 'Delete'}
                </button>
              </div>
              <p className="text-sm text-gray-500 mb-3">
                {ws.doc_count} document{ws.doc_count !== 1 ? 's' : ''}
              </p>
              <div className="flex flex-wrap gap-2 text-xs">
                {ws.jobs.completed > 0 && (
                  <span className="flex items-center gap-1">
                    <JobStatusBadge status="completed" /> {ws.jobs.completed}
                  </span>
                )}
                {ws.jobs.processing > 0 && (
                  <span className="flex items-center gap-1">
                    <JobStatusBadge status="processing" /> {ws.jobs.processing}
                  </span>
                )}
                {ws.jobs.queued > 0 && (
                  <span className="flex items-center gap-1">
                    <JobStatusBadge status="queued" /> {ws.jobs.queued}
                  </span>
                )}
                {ws.jobs.failed > 0 && (
                  <span className="flex items-center gap-1">
                    <JobStatusBadge status="failed" /> {ws.jobs.failed}
                  </span>
                )}
              </div>
              {ws.last_activity && (
                <p className="text-xs text-gray-400 mt-3">
                  Last activity: {new Date(ws.last_activity).toLocaleString()}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
