import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import Icon from './Icon.jsx'
import { SimilarityScore } from './PaperCard.jsx'
import SimilarityGraph from './SimilarityGraph.jsx'

export default function DetailPanel({ paperId, onClose, onOpenPaper, bookmarked, onBookmark, activityDisabled }) {
  const [paper, setPaper] = useState(null)
  const [recommendations, setRecommendations] = useState(null)
  const [loadingPaper, setLoadingPaper] = useState(true)
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [error, setError] = useState('')
  const [recommendationError, setRecommendationError] = useState('')
  const [bibtexCopied, setBibtexCopied] = useState(false)
  const [recsViewMode, setRecsViewMode] = useState('list')
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

  function copyBibtex() {
    if (!paper) return
    const firstWord = (paper.title.split(' ')[0] || 'paper').replace(/[^a-zA-Z0-9]/g, '').toLowerCase()
    const citeKey = `${firstWord}_arxiv`
    const bibtex = `@article{${citeKey},
  title = {${paper.title.replace(/[{}]/g, '')}},
  abstract = {${(paper.abstract || '').replace(/[{}]/g, '')}},
  keywords = {${(paper.terms || []).join(', ')}},
  year = {2021}
}`
    navigator.clipboard?.writeText?.(bibtex)?.then(() => {
      setBibtexCopied(true)
      setTimeout(() => setBibtexCopied(false), 2500)
    })?.catch(() => {})
  }

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

            <div className="detail-actions-bar">
              <a
                className="action-pill external-link"
                href={`https://scholar.google.com/scholar?q=${encodeURIComponent(paper.title)}`}
                target="_blank"
                rel="noreferrer"
                title="Search on Google Scholar"
              >
                Google Scholar ↗
              </a>
              <a
                className="action-pill external-link"
                href={`https://arxiv.org/search/?query=${encodeURIComponent(paper.title)}&searchtype=title`}
                target="_blank"
                rel="noreferrer"
                title="Search on arXiv"
              >
                arXiv Search ↗
              </a>
              <button
                className="action-pill bibtex-button"
                type="button"
                onClick={copyBibtex}
                title="Copy BibTeX Citation"
              >
                {bibtexCopied ? '✓ Copied BibTeX!' : 'Copy BibTeX'}
              </button>
            </div>

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
                  <div className="recs-view-toggle">
                    <button
                      className={`toggle-btn ${recsViewMode === 'list' ? 'is-active' : ''}`}
                      type="button"
                      onClick={() => setRecsViewMode('list')}
                      title="View as list"
                    >
                      List
                    </button>
                    <button
                      className={`toggle-btn ${recsViewMode === 'graph' ? 'is-active' : ''}`}
                      type="button"
                      onClick={() => setRecsViewMode('graph')}
                      title="Interactive Similarity Network Graph"
                    >
                      Graph 🕸️
                    </button>
                    <span className="result-count">{recommendations.length}</span>
                  </div>
                </div>

                {recsViewMode === 'graph' ? (
                  <SimilarityGraph
                    seedPaper={paper}
                    recommendations={recommendations}
                    onOpenPaper={onOpenPaper}
                  />
                ) : (
                  recommendations.map((item) => (
                    <article className="recommendation-item" key={item.paper_id}>
                      <button className="recommendation-title" onClick={() => onOpenPaper(item.paper_id)}>{item.title}</button>
                      <div className="tag-list recommendation-tags">{(item.terms || []).slice(0, 3).map((term) => <span className="category-tag" key={term}>{term}</span>)}</div>
                      
                      {item.matching_terms && item.matching_terms.length > 0 && (
                        <div className="concept-overlap">
                          <span className="concept-label"><Icon name="spark" size={12} /> Key overlap:</span>
                          <div className="concept-tags">
                            {item.matching_terms.slice(0, 3).map((term) => (
                              <span className="concept-pill" key={term}>{term}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      <SimilarityScore value={item.similarity} />
                      <p>{item.abstract?.trim() || 'No abstract text is available for this record.'}</p>

                      <div className="recommendation-footer">
                        <div className="recommendation-links">
                          <a
                            className="scholar-link"
                            href={`https://scholar.google.com/scholar?q=${encodeURIComponent(item.title)}`}
                            target="_blank"
                            rel="noreferrer"
                            title="Search paper on Google Scholar"
                          >
                            Scholar ↗
                          </a>
                          <a
                            className="scholar-link"
                            href={`https://arxiv.org/search/?query=${encodeURIComponent(item.title)}&searchtype=title`}
                            target="_blank"
                            rel="noreferrer"
                            title="Search on arXiv"
                          >
                            arXiv ↗
                          </a>
                        </div>
                        <button className="text-action" onClick={() => onOpenPaper(item.paper_id)} type="button">
                          Explore paper <Icon name="arrow" size={13} />
                        </button>
                      </div>
                    </article>
                  ))
                )}
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
