import { useState } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useGraph } from '../hooks/useGraph';
import GraphViewer from '../components/GraphViewer';

export default function GraphPage() {
  const { workspace } = useWorkspace();
  const { graphData, loading, error, fetchGraph, fetchFullGraph } = useGraph(workspace);
  const [query, setQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState(null);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (query.trim()) fetchGraph(query.trim());
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Knowledge Graph</h1>

      <form onSubmit={handleSubmit} className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter graph by query..."
          className="flex-1 border rounded px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Filter'}
        </button>
        <button
          type="button"
          onClick={() => { setQuery(''); fetchFullGraph(); }}
          disabled={loading}
          className="bg-gray-200 text-gray-700 px-4 py-2 rounded text-sm hover:bg-gray-300 disabled:opacity-50"
        >
          Show All
        </button>
      </form>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm mb-4">{error}</div>
      )}

      <div className="relative">
        <GraphViewer graphData={graphData} onNodeClick={(node) => setSelectedNode(node)} />
        {selectedNode && (
          <div className="absolute top-2 right-2 w-64 bg-white border rounded shadow-lg p-4 z-10">
            <h3 className="font-semibold text-sm mb-2">{selectedNode.label}</h3>
            <p className="text-xs text-gray-500 mb-1">Type: {selectedNode.type}</p>
            {selectedNode.description && (
              <p className="text-xs text-gray-600 mt-2">{selectedNode.description}</p>
            )}
            <button
              onClick={() => setSelectedNode(null)}
              className="mt-3 text-xs text-gray-400 hover:text-gray-600"
            >
              Close
            </button>
          </div>
        )}
      </div>

      <p className="text-xs text-gray-400 mt-2">
        {graphData.nodes.length} entities, {graphData.links.length} relations
      </p>
    </div>
  );
}
