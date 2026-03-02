import { useState, useCallback, useEffect } from 'react';
import { queryGraph, getGraphLabels, getGraphByLabel } from '../api';

export function useGraph(workspace) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const buildGraph = useCallback((nodes, edges) => {
    const nodeMap = new Map();
    nodes.forEach((n) => {
      const id = n.id || n.entity_name || n.name;
      if (id && !nodeMap.has(id)) {
        const props = n.properties || {};
        nodeMap.set(id, {
          id,
          label: props.entity_id || id,
          type: props.entity_type || n.entity_type || n.type || 'unknown',
          description: props.description || n.description || '',
        });
      }
    });

    const links = [];
    edges.forEach((e) => {
      const src = e.source || e.src_id;
      const tgt = e.target || e.tgt_id;
      if (src && tgt) {
        if (!nodeMap.has(src)) nodeMap.set(src, { id: src, label: src, type: 'unknown' });
        if (!nodeMap.has(tgt)) nodeMap.set(tgt, { id: tgt, label: tgt, type: 'unknown' });
        const props = e.properties || {};
        links.push({
          source: src,
          target: tgt,
          label: props.description || e.description || e.relation || e.type || '',
        });
      }
    });

    return { nodes: Array.from(nodeMap.values()), links };
  }, []);

  const fetchFullGraph = useCallback(async () => {
    if (!workspace) return;
    try {
      setLoading(true);
      setError(null);
      const labels = await getGraphLabels(workspace);
      const allNodes = [];
      const allEdges = [];
      for (const label of labels) {
        const g = await getGraphByLabel(label, workspace);
        allNodes.push(...(g.nodes || []));
        allEdges.push(...(g.edges || []));
      }
      setGraphData(buildGraph(allNodes, allEdges));
    } catch (e) {
      setError(e.message);
      setGraphData({ nodes: [], links: [] });
    } finally {
      setLoading(false);
    }
  }, [workspace, buildGraph]);

  const fetchGraph = useCallback(async (query, mode = 'local') => {
    if (!workspace) return;
    try {
      setLoading(true);
      setError(null);
      const data = await queryGraph(query, workspace, mode);
      const entities = data.data?.entities || data.entities || [];
      const relations = data.data?.relationships || data.data?.relations || data.relationships || data.relations || [];
      // Convert query/data entities to node format
      const nodes = entities.map((e) => ({
        id: e.entity_name || e.name,
        entity_name: e.entity_name || e.name,
        entity_type: e.entity_type || e.type,
        description: e.description,
      }));
      const edges = relations.map((r) => ({
        source: r.src_id || r.source,
        target: r.tgt_id || r.target,
        description: r.description || r.relation,
      }));
      setGraphData(buildGraph(nodes, edges));
    } catch (e) {
      setError(e.message);
      setGraphData({ nodes: [], links: [] });
    } finally {
      setLoading(false);
    }
  }, [workspace, buildGraph]);

  // Re-fetch on mount (page navigation) and workspace change
  useEffect(() => {
    fetchFullGraph();
  }, [fetchFullGraph]);

  return { graphData, loading, error, fetchGraph, fetchFullGraph };
}
