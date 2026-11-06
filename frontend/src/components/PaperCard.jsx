import Icon from './Icon.jsx'

export function SimilarityScore({ value }) {
  if (typeof value !== 'number') return null
  const pct = Math.min(100, Math.max(0, Math.round(value * 100)))
  return (
    <span className="similarity-score" title={`Cosine similarity score: ${value.toFixed(4)}`}>
      <span className="match-badge">{pct}% match</span>
      <span className="score-raw">{value.toFixed(3)}</span>
    </span>
  )
}

export default function PaperCard({ paper, onOpen, bookmarked, onBookmark, bookmarkDisabled, bookmarkPending = false, compact = false }) {
  const preview = paper.abstract?.trim() || 'No abstract text is available for this record.'
  return (
    <article className={`paper-card ${compact ? 'paper-card-compact' : ''}`}>
      <div className="paper-card-topline">
        <div className="tag-list" aria-label="Categories">
          {(paper.terms || []).slice(0, 4).map((term) => <span className="category-tag" key={term}>{term}</span>)}
          {(paper.terms || []).length > 4 && <span className="category-more">+{paper.terms.length - 4}</span>}
        </div>
        <button
          className={`icon-button bookmark-button ${bookmarked ? 'is-saved' : ''} ${bookmarkPending ? 'is-pending' : ''}`}
          type="button"
          aria-label={bookmarkPending ? (bookmarked ? 'Removing bookmark' : 'Saving bookmark') : bookmarked ? 'Saved. Remove bookmark' : 'Save paper'}
          aria-pressed={bookmarked}
          title={bookmarkDisabled ? 'Activity storage is unavailable' : bookmarkPending ? (bookmarked ? 'Removing bookmark' : 'Saving bookmark') : bookmarked ? 'Saved · Remove bookmark' : 'Save paper'}
          disabled={bookmarkDisabled || bookmarkPending}
          onClick={() => onBookmark(paper)}
        >
          {bookmarkPending ? <span className="bookmark-spinner" aria-hidden="true" /> : <Icon name="bookmark" size={17} />}
        </button>
      </div>
      <button className="paper-title-button" type="button" onClick={() => onOpen(paper.paper_id)}>
        <h3>{paper.title}</h3>
        <Icon name="chevron" size={18} />
      </button>
      {!compact && <p className="paper-abstract">{preview}{preview.length > 260 ? '…' : ''}</p>}

      {paper.matching_terms && paper.matching_terms.length > 0 && (
        <div className="concept-overlap" aria-label="Key matching concepts">
          <span className="concept-label"><Icon name="spark" size={12} /> Key overlap:</span>
          <div className="concept-tags">
            {paper.matching_terms.slice(0, 3).map((term) => (
              <span className="concept-pill" key={term}>{term}</span>
            ))}
          </div>
        </div>
      )}

      <div className="paper-card-footer">
        {typeof paper.similarity === 'number' ? <SimilarityScore value={paper.similarity} /> : <span className="paper-meta">Research paper</span>}
        <div className="footer-actions">
          <a
            className="scholar-link"
            href={`https://scholar.google.com/scholar?q=${encodeURIComponent(paper.title)}`}
            target="_blank"
            rel="noreferrer"
            title="Search paper on Google Scholar"
          >
            Scholar
          </a>
          <button className="text-action" onClick={() => onOpen(paper.paper_id)} type="button">View details <Icon name="arrow" size={14} /></button>
        </div>
      </div>
    </article>
  )
}
