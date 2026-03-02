import { useState } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useJobs } from '../hooks/useJobs';
import JobTable from '../components/JobTable';

const FILTERS = [
  { label: 'All', value: null },
  { label: 'Queued', value: 'queued' },
  { label: 'Processing', value: 'processing' },
  { label: 'Indexing', value: 'indexing' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
];

export default function JobsPage() {
  const { workspace } = useWorkspace();
  const [statusFilter, setStatusFilter] = useState(null);
  const { jobs, loading } = useJobs(workspace, statusFilter);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Jobs</h1>

      <div className="flex gap-1 mb-4">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setStatusFilter(f.value)}
            className={`px-3 py-1.5 rounded text-sm ${
              statusFilter === f.value
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-gray-400 text-sm">Loading...</p>
      ) : (
        <JobTable jobs={jobs} />
      )}
    </div>
  );
}
