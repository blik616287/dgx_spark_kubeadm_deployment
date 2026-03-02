import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { WorkspaceProvider } from './hooks/useWorkspaceContext';
import Layout from './components/Layout';
import DashboardPage from './pages/DashboardPage';
import IngestPage from './pages/IngestPage';
import JobsPage from './pages/JobsPage';
import DocumentsPage from './pages/DocumentsPage';
import GraphPage from './pages/GraphPage';
import QueryPage from './pages/QueryPage';

export default function App() {
  return (
    <WorkspaceProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="ingest" element={<IngestPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="graph" element={<GraphPage />} />
            <Route path="query" element={<QueryPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </WorkspaceProvider>
  );
}
