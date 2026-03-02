import { useState } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useWorkspaces } from '../hooks/useWorkspaces';

export default function WorkspaceSelector() {
  const { workspace, switchWorkspace } = useWorkspace();
  const { workspaces } = useWorkspaces();
  const [custom, setCustom] = useState('');
  const [showInput, setShowInput] = useState(false);

  const names = workspaces.map((w) => w.name);
  if (!names.includes(workspace)) names.push(workspace);

  const handleCreate = () => {
    const name = custom.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '-');
    if (name) {
      switchWorkspace(name);
      setCustom('');
      setShowInput(false);
    }
  };

  return (
    <div className="flex items-center gap-3">
      <label className="text-sm font-medium text-gray-500 whitespace-nowrap">Workspace</label>
      <select
        value={workspace}
        onChange={(e) => {
          if (e.target.value === '__new__') {
            setShowInput(true);
          } else {
            setShowInput(false);
            switchWorkspace(e.target.value);
          }
        }}
        className="bg-white text-gray-900 text-sm rounded px-3 py-1.5 border border-gray-300 focus:border-blue-500 focus:outline-none min-w-[180px]"
      >
        {names.map((n) => (
          <option key={n} value={n}>{n}</option>
        ))}
        <option value="__new__">+ New workspace...</option>
      </select>
      {showInput && (
        <div className="flex items-center gap-1">
          <input
            type="text"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            placeholder="workspace-name"
            className="text-sm rounded px-2 py-1.5 border border-gray-300 focus:border-blue-500 focus:outline-none w-44"
            autoFocus
          />
          <button onClick={handleCreate} className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700">
            Create
          </button>
          <button onClick={() => setShowInput(false)} className="text-sm text-gray-400 hover:text-gray-600 px-1">
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
