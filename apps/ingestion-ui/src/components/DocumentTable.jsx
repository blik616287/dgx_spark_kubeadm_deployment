import { useState } from 'react';
import { deleteDocument, deleteLightragDocs, downloadDocumentUrl } from '../api';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import JobStatusBadge from './JobStatusBadge';

export default function DocumentTable({ documents, lightragDocs, onRefresh }) {
  const { workspace } = useWorkspace();
  const [deleting, setDeleting] = useState(null);

  // Build map of all LightRAG docs
  const lrDocMap = new Map();
  if (lightragDocs) {
    for (const [, docs] of Object.entries(lightragDocs)) {
      for (const doc of docs) {
        lrDocMap.set(doc.id, doc);
      }
    }
  }

  const handleDelete = async (docId) => {
    if (!confirm('Delete this document and its knowledge graph data?')) return;
    try {
      setDeleting(docId);
      await deleteDocument(docId);
      onRefresh();
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleting(null);
    }
  };

  const handleDeleteLrDoc = async (lrDocId) => {
    if (!confirm('Delete this document from the knowledge graph?')) return;
    try {
      setDeleting(lrDocId);
      await deleteLightragDocs([lrDocId], workspace);
      onRefresh();
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleting(null);
    }
  };

  // Find LightRAG docs not tracked by orchestrator (orphans)
  const orchFileNames = new Set(documents.map((d) => d.result?.file_name).filter(Boolean));
  const orphanedLrDocs = [];
  for (const [, doc] of lrDocMap) {
    const fp = doc.file_path || '';
    const matched = orchFileNames.has(fp) || [...orchFileNames].some((n) => fp.endsWith(`/${n}`));
    if (!matched) orphanedLrDocs.push(doc);
  }

  if (!documents.length && !orphanedLrDocs.length) {
    return <p className="text-gray-400 text-sm py-4">No documents found.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-3 font-medium">File</th>
            <th className="py-2 pr-3 font-medium">Type</th>
            <th className="py-2 pr-3 font-medium">Status</th>
            <th className="py-2 pr-3 font-medium">Created</th>
            <th className="py-2 pr-3 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((d) => {
            const fileName = d.result?.file_name || d.job_type || '-';
            return (
              <tr key={d.job_id} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-2 pr-3 max-w-[200px] truncate" title={fileName}>{fileName}</td>
                <td className="py-2 pr-3">{d.job_type}</td>
                <td className="py-2 pr-3"><JobStatusBadge status={d.status} /></td>
                <td className="py-2 pr-3 text-xs">{new Date(d.created_at).toLocaleString()}</td>
                <td className="py-2 pr-3 space-x-2">
                  <a
                    href={downloadDocumentUrl(d.doc_id)}
                    className="text-blue-600 hover:underline text-xs"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download
                  </a>
                  <button
                    onClick={() => handleDelete(d.doc_id)}
                    disabled={deleting === d.doc_id}
                    className="text-red-600 hover:underline text-xs disabled:opacity-50"
                  >
                    {deleting === d.doc_id ? 'Deleting...' : 'Delete'}
                  </button>
                </td>
              </tr>
            );
          })}
          {orphanedLrDocs.map((doc) => (
            <tr key={doc.id} className="border-b border-gray-100 hover:bg-gray-50 bg-yellow-50">
              <td className="py-2 pr-3 max-w-[200px] truncate" title={doc.file_path}>
                {doc.file_path || doc.id}
                <span className="ml-1 text-xs text-yellow-600">(graph only)</span>
              </td>
              <td className="py-2 pr-3 text-xs text-gray-400">lightrag</td>
              <td className="py-2 pr-3 text-xs">{doc.status}</td>
              <td className="py-2 pr-3 text-xs">
                {doc.created_at ? new Date(doc.created_at).toLocaleString() : '-'}
              </td>
              <td className="py-2 pr-3">
                <button
                  onClick={() => handleDeleteLrDoc(doc.id)}
                  disabled={deleting === doc.id}
                  className="text-red-600 hover:underline text-xs disabled:opacity-50"
                >
                  {deleting === doc.id ? 'Deleting...' : 'Delete'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
