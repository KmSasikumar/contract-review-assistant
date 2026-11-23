import { useEffect, useRef, useState } from 'react'
import { apiJson } from '../api.js'

// The contract as clause-sized chunks, each with its page and section.
// Jump-to-clause scrolls to a chunk and highlights it.
export default function ContractViewer({ contract, getToken, highlightChunkId }) {
  const [chunks, setChunks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const refs = useRef({})

  useEffect(() => {
    apiJson(getToken, `/api/contracts/${contract.id}/text`)
      .then(setChunks)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contract.id])

  useEffect(() => {
    if (!highlightChunkId || !refs.current[highlightChunkId]) return
    refs.current[highlightChunkId].scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [highlightChunkId, chunks])

  if (loading) return <p className="muted">Loading contract text…</p>
  if (error) return <p className="error">{error}</p>
  if (chunks.length === 0) return <p className="muted">No text extracted from this contract.</p>

  return (
    <div className="contract-text">
      {chunks.map((ch) => (
        <div
          key={ch.id}
          id={`chunk-${ch.id}`}
          ref={(el) => {
            if (el) refs.current[ch.id] = el
          }}
          className={
            highlightChunkId === ch.id ? 'chunk chunk-highlight' : 'chunk'
          }
        >
          <div className="chunk-meta">
            {ch.section ? `${ch.section} · ` : ''}
            {ch.page ? `page ${ch.page}` : ''}
          </div>
          <p>{ch.text}</p>
        </div>
      ))}
    </div>
  )
}
