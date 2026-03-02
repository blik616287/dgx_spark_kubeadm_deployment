const colors = {
  queued: 'bg-blue-100 text-blue-700',
  processing: 'bg-yellow-100 text-yellow-700',
  indexing: 'bg-purple-100 text-purple-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
};

export default function JobStatusBadge({ status }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-600'}`}>
      {status}
    </span>
  );
}
