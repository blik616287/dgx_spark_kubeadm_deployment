import { useWorkspace } from '../hooks/useWorkspaceContext';
import QueryPanel from '../components/QueryPanel';

export default function QueryPage() {
  const { workspace } = useWorkspace();

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Query</h1>
      <QueryPanel />
    </div>
  );
}
