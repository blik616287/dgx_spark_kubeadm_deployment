import { useRef, useCallback, useEffect, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

const TYPE_COLORS = {
  person: '#3b82f6',
  organization: '#10b981',
  location: '#f59e0b',
  event: '#ef4444',
  concept: '#8b5cf6',
  technology: '#06b6d4',
  function: '#14b8a6',
  class: '#6366f1',
  module: '#f97316',
  file: '#84cc16',
  unknown: '#9ca3af',
};

function getColor(type) {
  const key = (type || '').toLowerCase();
  return TYPE_COLORS[key] || TYPE_COLORS.unknown;
}

const ZOOM_STEP = 1.5;

export default function GraphViewer({ graphData, onNodeClick }) {
  const fgRef = useRef();
  const containerRef = useRef();
  const [dimensions, setDimensions] = useState({ width: 0, height: 600 });

  const zoomIn = () => {
    const fg = fgRef.current;
    if (fg) fg.zoom(fg.zoom() * ZOOM_STEP, 300);
  };
  const zoomOut = () => {
    const fg = fgRef.current;
    if (fg) fg.zoom(fg.zoom() / ZOOM_STEP, 300);
  };
  const zoomFit = () => {
    const fg = fgRef.current;
    if (fg) fg.zoomToFit(400, 40);
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0) {
        setDimensions({
          width: Math.floor(rect.width),
          height: Math.max(500, window.innerHeight - 280),
        });
      }
    };
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (fgRef.current && graphData.nodes.length) {
      setTimeout(() => fgRef.current.zoomToFit(400, 40), 1000);
    }
  }, [graphData, dimensions]);

  const paintNode = useCallback((node, ctx) => {
    const r = 5;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = getColor(node.type);
    ctx.fill();

    ctx.font = '3px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#374151';
    ctx.fillText(node.label, node.x, node.y + r + 1);
  }, []);

  const hasData = graphData.nodes.length > 0;
  const ready = hasData && dimensions.width > 0;

  return (
    <div ref={containerRef} className="border rounded bg-white w-full">
      {!hasData && (
        <div className="text-gray-400 text-sm py-8 text-center">
          No graph data available for this workspace.
        </div>
      )}
      {ready && (
        <div className="relative">
        <div className="absolute top-2 left-2 z-10 flex flex-col gap-1">
          <button onClick={zoomIn} className="w-8 h-8 bg-white border rounded shadow text-lg leading-none hover:bg-gray-50" title="Zoom in">+</button>
          <button onClick={zoomOut} className="w-8 h-8 bg-white border rounded shadow text-lg leading-none hover:bg-gray-50" title="Zoom out">&minus;</button>
          <button onClick={zoomFit} className="w-8 h-8 bg-white border rounded shadow text-xs leading-none hover:bg-gray-50" title="Fit to screen">Fit</button>
        </div>
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          nodeCanvasObject={paintNode}
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.beginPath();
            ctx.arc(node.x, node.y, 5, 0, 2 * Math.PI);
            ctx.fillStyle = color;
            ctx.fill();
          }}
          linkColor={() => '#d1d5db'}
          linkWidth={0.5}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          onNodeClick={onNodeClick}
          width={dimensions.width}
          height={dimensions.height}
        />
        </div>
      )}
      <div className="flex flex-wrap gap-2 p-2 border-t text-xs">
        {Object.entries(TYPE_COLORS).filter(([k]) => k !== 'unknown').map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}
