import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import Icon from './Icon.jsx'
import { SimilarityScore } from './PaperCard.jsx'

export default function DetailPanel({ paperId, onClose, onOpenPaper, bookmarked, onBookmark, activityDisabled }) {
  const [paper, setPaper] = useState(null)
  const [recommendations, setRecommendations] = useState(null)
  const [loadingPaper, setLoadingPaper] = useState(true)
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [error, setError] = useState('')
  const [recommendationError, setRecommendationError] = useState('')
  const recommendationRequestId = useRef(0)
  const [paperRetry, setPaperRetry] = useState(0)

  useEffect(() => {
    let active = true
    setPaper(null)
    setRecommendations(null)
    setError('')
    setLoadingPaper(true)
    setLoadingRecommendations(false)
    setRecommendationError('')
    recommendationRequestId.current += 1
    api.paper(paperId)
      .then((result) => { if (active) setPaper(result) })
      .catch((reason) => { if (active) setError(reason.message) })
      .finally(() => { if (active) setLoadingPaper(false) })
    return () => {
      active = false
      recommendationRequestId.current += 1
    }
  }, [paperId, paperRetry])

  async function findSimilar() {
    const requestId = ++recommendationRequestId.current
    const requestedPaperId = paperId
    setLoadingRecommendations(true)
    setRecommendationError('')
    try {
      const response = await api.recommendations(paperId, 5)
      if (recommendationRequestId.current === requestId) setRecommendations(response.recommendations || [])
    } catch (reason) {
      if (recommendationRequestId.current === requestId) setRecommendationError(reason.message)
    } finally {
      if (recommendationRequestId.current === requestId && requestedPaperId === paperId) setLoadingRecommendations(false)
    }
  }

  return (
    <>
      <button className="detail-scrim" aria-label="Close paper details" onClick={onClose} />
      <aside className="detail-panel" aria-label="Paper details">
        <div className="detail-panel-header">
          <span className="eyebrow">PAPER DETAILS</span>
          <button className="icon-button close-button" onClick={onClose} aria-label="Close details"><Icon name="close" /></button>
        </div>
        {loadingPaper ? <div className="detail-loading"><span className="spinner" /> Loading paper details…</div> : error ? (
          <div className="inline-error" role="alert">{error}<button className="text-action" type="button" onClick={() => setPaperRetry((attempt) => attempt + 1)}>Retry loading paper</button></div>
        ) : paper && (
          <div className="detail-content">
            <div className="tag-list detail-tags">{paper.terms.map((term) => <span className="category-tag" key={term}>{term}</span>)}</div>
            <h2>{paper.title}</h2>
            <div className="detail-rule" />
            <h3 className="section-kicker">ABSTRACT</h3>
            <p className="detail-abstract">{paper.abstract || 'No abstract text is available for this record.'}</p>
            <button className="primary-action full-width" onClick={findSimilar} disabled={loadingRecommendations}>
              {loadingRecommendations ? <span className="button-spinner" /> : <Icon name="spark" size={17} />}
              <span>{loadingRecommendations ? 'Finding papers…' : 'Find similar papers'}</span>
            </button>
            {recommendationError && <div className="inline-error" role="alert">{recommendationError}</div>}
            {recommendations && recommendations.length > 0 && (
              <section className="recommendations" aria-labelledby="recommendations-heading">
                <div className="recommendation-heading">
                  <div><span className="eyebrow">RELATED RESEARCH</span><h3 id="recommendations-heading">Similar papers</h3></div>
                  <span className="result-count">{recommendations.length}</span>
                </div>
                {recommendations.map((item) => (
                  <article className="recommendation-item" key={item.paper_id}>
                    <button className="recommendation-title" onClick={() => onOpenPaper(item.paper_id)}>{item.title}</button>
                    <div className="tag-list recommendation-tags">{(item.terms || []).slice(0, 3).map((term) => <span className="category-tag" key={term}>{term}</span>)}</div>
                    <SimilarityScore value={item.similarity} />
                    <p>{item.abstract?.trim() || 'No abstract text is available for this record.'}</p>
                  </article>
                ))}
              </section>
            )}
            {recommendations && recommendations.length === 0 && !loadingRecommendations && !recommendationError && (
              <p className="recommendation-hint">No recommendations were returned for this paper.</p>
            )}
          </div>
        )}
      </aside>
    </>
  )
}
