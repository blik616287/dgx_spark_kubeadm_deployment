import { useState } from 'react';
import { queryGraph, queryExplain } from '../api';
import { useWorkspace } from '../hooks/useWorkspaceContext';

const MODES = [
  { value: 'naive', label: 'Vector search' },
  { value: 'mix', label: 'Vector + Graph' },
  { value: 'local', label: 'Graph (local)' },
  { value: 'global', label: 'Graph (global)' },
  { value: 'hybrid', label: 'Graph (hybrid)' },
];

function ChunkCard({ chunk, idx }) {
  const [expanded, setExpanded] = useState(false);
  const content = chunk.content || '';
  const preview = content.length > 300 && !expanded ? content.slice(0, 300) + '...' : content;
  return (
    <div className="border rounded p-3 text-sm bg-gray-50">
      <div className="flex justify-between items-start mb-1">
        <span className="font-medium text-gray-700">Chunk #{idx + 1}</span>
        {chunk.file_path && (
          <span className="text-xs text-gray-400 truncate max-w-[50%]" title={chunk.file_path}>
            {chunk.file_path}
          </span>
        )}
      </div>
      <p className="whitespace-pre-wrap text-gray-600">{preview}</p>
      {content.length > 300 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-blue-600 text-xs mt-1 hover:underline"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}

function EntityRow({ entity }) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="py-1 px-2 font-medium text-sm">{entity.entity_name || entity.name || '?'}</td>
      <td className="py-1 px-2 text-xs text-gray-500">{entity.entity_type || entity.type || '?'}</td>
      <td className="py-1 px-2 text-xs text-gray-600 max-w-md truncate" title={entity.description}>
        {entity.description || '-'}
      </td>
    </tr>
  );
}

function RelationRow({ rel }) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="py-1 px-2 text-sm font-medium">{rel.src_id || rel.source || '?'}</td>
      <td className="py-1 px-2 text-xs text-gray-400 text-center">→</td>
      <td className="py-1 px-2 text-sm font-medium">{rel.tgt_id || rel.target || '?'}</td>
      <td className="py-1 px-2 text-xs text-gray-600 max-w-sm truncate" title={rel.description}>
        {rel.description || '-'}
      </td>
    </tr>
  );
}

function Section({ title, count, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border rounded">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex justify-between items-center px-3 py-2 bg-gray-50 hover:bg-gray-100 text-sm font-medium"
      >
        <span>{title} ({count})</span>
        <span className="text-gray-400">{open ? '▾' : '▸'}</span>
      </button>
      {open && <div className="p-3">{children}</div>}
    </div>
  );
}

export default function QueryPanel() {
  const { workspace } = useWorkspace();
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('naive');
  const [result, setResult] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    try {
      setLoading(true);
      setError(null);
      setExplanation(null);
      const data = await queryGraph(query, workspace, mode);
      setResult(data);
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const handleExplain = async () => {
    if (!query.trim()) return;
    try {
      setExplaining(true);
      setError(null);
      const data = await queryExplain(query, workspace, mode === 'naive' ? 'mix' : mode);
      const text = typeof data === 'string' ? data : data.response || data.content || JSON.stringify(data, null, 2);
      setExplanation(text);
    } catch (err) {
      setError(err.message);
    } finally {
      setExplaining(false);
    }
  };

  const d = result?.data || {};
  const entities = d.entities || [];
  const relationships = d.relationships || d.relations || [];
  const chunks = d.chunks || [];
  const hasResults = entities.length > 0 || relationships.length > 0 || chunks.length > 0;

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search your knowledge graph..."
          className="flex-1 border rounded px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="border rounded px-2 py-2 text-sm bg-white"
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
        <button
          type="button"
          onClick={handleExplain}
          disabled={explaining || !query.trim()}
          className="bg-purple-600 text-white px-4 py-2 rounded text-sm hover:bg-purple-700 disabled:opacity-50"
        >
          {explaining ? 'Thinking...' : 'Explain'}
        </button>
      </form>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">{error}</div>
      )}

      {explanation && (
        <div className="bg-purple-50 border border-purple-200 rounded p-4">
          <div className="flex justify-between items-center mb-2">
            <span className="text-xs font-medium text-purple-600">LLM Explanation</span>
            <button onClick={() => setExplanation(null)} className="text-xs text-gray-400 hover:text-gray-600">dismiss</button>
          </div>
          <div className="text-sm whitespace-pre-wrap text-gray-800">{explanation}</div>
        </div>
      )}

      {result && !hasResults && !explanation && (
        <div className="text-gray-400 text-sm text-center py-6">No results found.</div>
      )}

      {hasResults && (
        <div className="space-y-3">
          <div className="text-xs text-gray-400">
            {entities.length} entities, {relationships.length} relationships, {chunks.length} chunks
            {result?.metadata?.query_mode && ` — mode: ${result.metadata.query_mode}`}
          </div>

          {chunks.length > 0 && (
            <Section title="Chunks" count={chunks.length} defaultOpen={true}>
              <div className="space-y-2">
                {chunks.map((c, i) => <ChunkCard key={c.chunk_id || i} chunk={c} idx={i} />)}
              </div>
            </Section>
          )}

          {entities.length > 0 && (
            <Section title="Entities" count={entities.length} defaultOpen={true}>
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b text-xs text-gray-400">
                    <th className="py-1 px-2">Name</th>
                    <th className="py-1 px-2">Type</th>
                    <th className="py-1 px-2">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {entities.map((e, i) => <EntityRow key={i} entity={e} />)}
                </tbody>
              </table>
            </Section>
          )}

          {relationships.length > 0 && (
            <Section title="Relationships" count={relationships.length} defaultOpen={false}>
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b text-xs text-gray-400">
                    <th className="py-1 px-2">Source</th>
                    <th className="py-1 px-2"></th>
                    <th className="py-1 px-2">Target</th>
                    <th className="py-1 px-2">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {relationships.map((r, i) => <RelationRow key={i} rel={r} />)}
                </tbody>
              </table>
            </Section>
          )}
        </div>
      )}
    </div>
  );
}
