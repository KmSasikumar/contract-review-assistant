import { useEffect, useState } from 'react'
import { apiJson } from '../api.js'

const STATUS_LABEL = {
  found: 'Found',
  not_found: 'Not found',
  unclear: 'Unclear',
}

// Clicking a quote jumps to the full clause in the Contract text tab.
export default function ReviewView({ contract, getToken, onJumpToClause }) {
  const [review, setReview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (contract.status !== 'reviewed') {
      setLoading(false)
      return
    }
    setLoading(true)
    apiJson(getToken, `/api/contracts/${contract.id}/review`)
      .then(setReview)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contract.id, contract.status])

  if (contract.status === 'processing') {
    return <p className="muted">The review is still running — it appears here when it finishes.</p>
  }
  if (contract.status === 'failed') {
    return <p className="muted">No review yet — the review failed. Use “Retry review” above.</p>
  }
  if (loading) return <p className="muted">Loading the review…</p>
  if (error) return <p className="error">{error}</p>
  if (!review || review.items.length === 0) {
    return <p className="muted">No review items yet.</p>
  }

  return (
    <div>
      {review.risk_flags.length > 0 && (
        <div className="risk-box" role="alert">
          <strong>Risk flags</strong>
          <ul>
            {review.risk_flags.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      <ul className="review-list">
        {review.items.map((item) => (
          <li key={item.key} className={`review-item status-${item.status}`}>
            <div className="review-head">
              <strong>{item.label}</strong>
              <span className={`badge badge-${item.status}`}>{STATUS_LABEL[item.status]}</span>
            </div>
            <p>{item.summary}</p>
            {item.status === 'found' && item.quote && (
              <blockquote
                className="quote"
                title="Click to see the full clause in the contract"
                onClick={() => item.chunk_id && onJumpToClause(item.chunk_id)}
              >
                “{item.quote}”
                <footer>
                  {item.section ? `${item.section} · ` : ''}
                  {item.page ? `page ${item.page}` : 'page unknown'}
                  {!item.quote_verified && ' · quote could not be verified'}
                  {item.chunk_id && ' · click to see the full clause'}
                </footer>
              </blockquote>
            )}
            {item.status === 'not_found' && (
              <p className="muted">Not found in the contract — nothing was assumed.</p>
            )}
            {item.status === 'unclear' && (
              <p className="muted">
                Unclear — the contract text on this point is ambiguous, or the quoted text
                could not be verified in the contract.
              </p>
            )}
          </li>
        ))}
      </ul>
      <p className="muted">
        Every quote above was checked word for word against the contract text by the backend.
        A finding is only “Found” when its quote was verified.
      </p>
    </div>
  )
}
