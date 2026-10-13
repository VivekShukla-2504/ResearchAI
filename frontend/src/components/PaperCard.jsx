import Icon from './Icon.jsx'

export function SimilarityScore({ value }) {
  if (typeof value !== 'number') return null
  return <span className="similarity-score">Similarity score <strong>{value.toFixed(3)}</strong></span>
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
      <div className="paper-card-footer">
        {typeof paper.similarity === 'number' ? <SimilarityScore value={paper.similarity} /> : <span className="paper-meta">Research paper</span>}
        <button className="text-action" onClick={() => onOpen(paper.paper_id)} type="button">View details <Icon name="arrow" size={14} /></button>
      </div>
    </article>
  )
}
