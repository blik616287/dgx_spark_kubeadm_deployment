import { useState } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useJobs } from '../hooks/useJobs';
import { ingestDocument, ingestCodebase } from '../api';
import FileDropZone from '../components/FileDropZone';
import JobTable from '../components/JobTable';

export default function IngestPage() {
  const { workspace } = useWorkspace();
  const { jobs, refresh } = useJobs(workspace);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState(null);

  const handleUpload = async (file, type) => {
    try {
      setUploading(true);
      setMessage(null);
      const result = type === 'codebase'
        ? await ingestCodebase(file, workspace)
        : await ingestDocument(file, workspace);
      setMessage({ type: 'success', text: `Queued: ${file.name} (job ${result.job_id?.slice(0, 8)})` });
      refresh();
    } catch (e) {
      setMessage({ type: 'error', text: `Upload failed: ${e.message}` });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Ingest Documents</h1>

      <FileDropZone onUpload={handleUpload} disabled={uploading} />

      {uploading && <p className="mt-3 text-sm text-blue-600">Uploading...</p>}

      {message && (
        <div className={`mt-3 p-3 rounded text-sm ${
          message.type === 'error' ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-green-50 text-green-700 border border-green-200'
        }`}>
          {message.text}
        </div>
      )}

      <h2 className="text-lg font-semibold mt-8 mb-3">Recent Jobs</h2>
      <JobTable jobs={jobs} />
    </div>
  );
}
