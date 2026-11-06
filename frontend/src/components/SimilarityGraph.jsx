import { useState } from 'react'
import Icon from './Icon.jsx'

export default function SimilarityGraph({ seedPaper, recommendations = [], onOpenPaper }) {
  const [hoveredId, setHoveredId] = useState(null)

  if (!seedPaper || recommendations.length === 0) return null

  const width = 520
  const height = 370
  const cx = width / 2
  const cy = height / 2 - 10
  const rx = 180
  const ry = 125

  const satellites = recommendations.map((paper, idx) => {
    const angle = (idx / recommendations.length) * 2 * Math.PI - Math.PI / 2
    const x = cx + rx * Math.cos(angle)
    const y = cy + ry * Math.sin(angle)
    const pct = Math.min(100, Math.max(0, Math.round((paper.similarity || 0) * 100)))
    const strokeWidth = Math.max(1.5, Math.min(6, (paper.similarity || 0.2) * 6))
    return {
      ...paper,
      x,
      y,
      pct,
      strokeWidth,
      angle,
    }
  })

  const hoveredPaper = satellites.find((s) => s.paper_id === hoveredId)

  return (
    <div className="similarity-graph-container" aria-label="Interactive Similarity Network Graph">
      <div className="graph-header-controls">
        <span className="graph-hint">
          <Icon name="spark" size={13} /> Click any satellite node to navigate • Edge thickness represents similarity
        </span>
      </div>

      <div className="graph-canvas-wrap">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="similarity-graph-svg"
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <linearGradient id="centerGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#7b6be6" />
              <stop offset="100%" stopColor="#51439e" />
            </linearGradient>
            <linearGradient id="satelliteGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#48c4cf" />
              <stop offset="100%" stopColor="#2c8d96" />
            </linearGradient>
            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Orbit Guide Line */}
          <ellipse
            cx={cx}
            cy={cy}
            rx={rx}
            ry={ry}
            fill="none"
            stroke="currentColor"
            className="graph-orbit-ring"
            strokeDasharray="4 6"
          />

          {/* Edges from Center to Satellites */}
          {satellites.map((sat) => {
            const isHovered = hoveredId === sat.paper_id
            const midX = (cx + sat.x) / 2
            const midY = (cy + sat.y) / 2
            return (
              <g key={`edge-${sat.paper_id}`} className="graph-edge-group">
                <line
                  x1={cx}
                  y1={cy}
                  x2={sat.x}
                  y2={sat.y}
                  stroke={isHovered ? '#7b6be6' : 'currentColor'}
                  strokeWidth={isHovered ? sat.strokeWidth + 2 : sat.strokeWidth}
                  className={`graph-edge-line ${isHovered ? 'is-active' : ''}`}
                />
                {/* Edge Match Badge */}
                <rect
                  x={midX - 20}
                  y={midY - 9}
                  width="40"
                  height="18"
                  rx="4"
                  className="edge-badge-bg"
                />
                <text
                  x={midX}
                  y={midY + 4}
                  textAnchor="middle"
                  className="edge-badge-text"
                >
                  {(sat.similarity ?? (sat.pct / 100)).toFixed(2)}
                </text>
              </g>
            )
          })}

          {/* Center Seed Paper Node */}
          <g className="graph-center-group">
            <circle
              cx={cx}
              cy={cy}
              r="40"
              fill="url(#centerGradient)"
              filter="url(#glow)"
              className="graph-center-circle"
            />
            <circle cx={cx} cy={cy} r="46" fill="none" stroke="#7b6be6" strokeWidth="1.5" opacity="0.4" />
            <text x={cx} y={cy - 4} textAnchor="middle" className="center-node-title">
              CURRENT
            </text>
            <text x={cx} y={cy + 10} textAnchor="middle" className="center-node-sub">
              PAPER
            </text>
          </g>

          {/* Satellite Recommendation Nodes */}
          {satellites.map((sat, i) => {
            const isHovered = hoveredId === sat.paper_id
            const r = isHovered ? 28 : 23
            const categoryTag = (sat.terms && sat.terms[0]) || 'AI'
            return (
              <g
                key={`node-${sat.paper_id}`}
                className="graph-satellite-group"
                transform={`translate(${sat.x}, ${sat.y})`}
                onMouseEnter={() => setHoveredId(sat.paper_id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => onOpenPaper(sat.paper_id)}
                tabIndex={0}
                role="button"
                aria-label={`Open similar paper: ${sat.title}`}
                onKeyDown={(e) => { if (e.key === 'Enter') onOpenPaper(sat.paper_id) }}
              >
                <circle
                  cx={0}
                  cy={0}
                  r={r}
                  fill="url(#satelliteGradient)"
                  className={`satellite-circle ${isHovered ? 'is-hovered' : ''}`}
                />
                <text x={0} y={4} textAnchor="middle" className="satellite-text">
                  {`#${i + 1}`}
                </text>
                <text x={0} y={r + 14} textAnchor="middle" className="satellite-cat-text">
                  {categoryTag}
                </text>
              </g>
            )
          })}
        </svg>

        {/* Hovered Node Rich Tooltip */}
        {hoveredPaper && (
          <div className="graph-tooltip-card">
            <div className="tooltip-topline">
              <span className="tooltip-match">
                Text similarity: {(hoveredPaper.similarity ?? (hoveredPaper.pct / 100)).toFixed(2)}
              </span>
              <span className="tooltip-id">{hoveredPaper.terms?.[0] || 'Paper'}</span>
            </div>
            <div className="tooltip-subline">Cosine text overlap · Title & abstract</div>
            <h4 className="tooltip-title">{hoveredPaper.title}</h4>
            {hoveredPaper.matching_terms && hoveredPaper.matching_terms.length > 0 && (
              <div className="tooltip-concepts">
                <span>Overlap:</span> {hoveredPaper.matching_terms.slice(0, 3).join(', ')}
              </div>
            )}
            <div className="tooltip-footer">Click node to explore paper details ↗</div>
          </div>
        )}
      </div>
    </div>
  )
}
