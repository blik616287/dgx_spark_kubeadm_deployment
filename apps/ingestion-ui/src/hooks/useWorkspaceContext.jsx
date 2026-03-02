import { createContext, useContext, useState, useCallback } from 'react';

const WorkspaceContext = createContext(null);

export function WorkspaceProvider({ children }) {
  const [workspace, setWorkspace] = useState(
    () => localStorage.getItem('graphrag-workspace') || 'default'
  );

  const switchWorkspace = useCallback((ws) => {
    setWorkspace(ws);
    localStorage.setItem('graphrag-workspace', ws);
  }, []);

  return (
    <WorkspaceContext.Provider value={{ workspace, switchWorkspace }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be inside WorkspaceProvider');
  return ctx;
}
