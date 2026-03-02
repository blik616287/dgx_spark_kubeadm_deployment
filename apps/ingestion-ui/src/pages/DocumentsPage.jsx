import { useState, useEffect, useCallback } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useDocuments } from '../hooks/useDocuments';
import { listLightragDocs } from '../api';
import DocumentTable from '../components/DocumentTable';

export default function DocumentsPage() {
  const { workspace } = useWorkspace();
  const { documents, loading, refresh } = useDocuments(workspace);
  const [lrDocs, setLrDocs] = useState(null);

  const fetchLr = useCallback(async () => {
    if (!workspace) return;
    try {
      const data = await listLightragDocs(workspace);
      setLrDocs(data.statuses || {});
    } catch {
      setLrDocs(null);
    }
  }, [workspace]);

  useEffect(() => { fetchLr(); }, [fetchLr]);

  const handleRefresh = () => {
    refresh();
    fetchLr();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold">Documents</h1>
        <button onClick={handleRefresh} className="text-sm text-blue-600 hover:underline">
          Refresh
        </button>
      </div>

      {loading ? (
        <p className="text-gray-400 text-sm">Loading...</p>
      ) : (
        <DocumentTable documents={documents} lightragDocs={lrDocs} onRefresh={handleRefresh} />
      )}
    </div>
  );
}
