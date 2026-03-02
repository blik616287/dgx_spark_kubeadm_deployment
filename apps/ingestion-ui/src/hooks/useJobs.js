import { useState, useEffect, useCallback, useRef } from 'react';
import { listJobs } from '../api';

export function useJobs(workspace, statusFilter, pollInterval = 3000) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listJobs(workspace, statusFilter);
      setJobs(data.jobs);
    } catch (e) {
      console.error('Failed to fetch jobs:', e);
    } finally {
      setLoading(false);
    }
  }, [workspace, statusFilter]);

  useEffect(() => {
    refresh();
    intervalRef.current = setInterval(refresh, pollInterval);
    return () => clearInterval(intervalRef.current);
  }, [refresh, pollInterval]);

  return { jobs, loading, refresh };
}
