import { useState, useEffect, useCallback } from 'react';
import { listJobs } from '../api';

export function useDocuments(workspace) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!workspace) return;
    try {
      setLoading(true);
      const data = await listJobs(workspace, null, 200);
      setDocuments(data.jobs);
    } catch (e) {
      console.error('Failed to fetch documents:', e);
    } finally {
      setLoading(false);
    }
  }, [workspace]);

  useEffect(() => { refresh(); }, [refresh]);

  return { documents, loading, refresh };
}
