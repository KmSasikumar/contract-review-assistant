import { useEffect, useState } from 'react'
import { SignIn, SignUp, UserButton, useAuth } from '@clerk/react'
import { apiJson, getHealth, uploadContract } from './api.js'
import ReviewView from './components/ReviewView.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import ContractViewer from './components/ContractViewer.jsx'

const MAX_MB = 20

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function formatDate(iso) {
  return new Date(iso).toLocaleString()
}

export default function App() {
  const { getToken, isLoaded, isSignedIn } = useAuth()
  const [health, setHealth] = useState(null)
  const [contracts, setContracts] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [authMode, setAuthMode] = useState('signin') // signin | signup

  async function refresh() {
    try {
      const list = await apiJson(getToken, '/api/contracts')
      setContracts(list)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
    if (isSignedIn) refresh()
    else setLoading(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSignedIn])

  async function onFile(file) {
    if (!file) return
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`That file is over the ${MAX_MB} MB limit.`)
      return
    }
    setUploading(true)
    setError('')
    try {
      const created = await uploadContract(getToken, file)
      setContracts((prev) => [created, ...prev])
      setSelectedId(created.id)
    } catch (e) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  async function onDelete(id) {
    if (!window.confirm('Delete this contract and its review and chat history?')) return
    try {
      await apiJson(getToken, `/api/contracts/${id}`, { method: 'DELETE' })
      setContracts((prev) => prev.filter((c) => c.id !== id))
      if (selectedId === id) setSelectedId(null)
    } catch (e) {
      setError(e.message)
    }
  }

  const selected = contracts.find((c) => c.id === selectedId) || null

  return (
    <div className="app">
      <header className="topbar">
        <h1>Contract Review Assistant</h1>
        {isSignedIn && <UserButton afterSignOutUrl="/" />}
      </header>

      {!isLoaded ? (
        <p className="muted">Loading…</p>
      ) : !isSignedIn ? (
        <div className="auth-wrap">
          {authMode === 'signin' ? (
            <>
              <SignIn routing="hash" />
              <p className="auth-switch">
                No account yet?{' '}
                <button type="button" onClick={() => setAuthMode('signup')}>
                  Sign up
                </button>
              </p>
            </>
          ) : (
            <>
              <SignUp routing="hash" />
              <p className="auth-switch">
                Already have an account?{' '}
                <button type="button" onClick={() => setAuthMode('signin')}>
                  Sign in
                </button>
              </p>
            </>
          )}
        </div>
      ) : (
        <>
        {health && !health.ai_configured && (
          <div className="notice">
            AI review is not configured yet — add <code>OPENROUTER_API_KEY</code> to the
            backend <code>.env</code> (see README). Uploads, lists and chat history still work.
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
            <button type="button" onClick={() => setError('')}>
              Dismiss
            </button>
          </div>
        )}

        <main className="layout">
          <section className="sidebar">
            <label className="upload-box">
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                disabled={uploading}
                onChange={(e) => {
                  onFile(e.target.files[0])
                  e.target.value = ''
                }}
              />
              {uploading ? 'Uploading…' : 'Upload a contract (PDF, DOCX, TXT, up to 20 MB)'}
            </label>

            {loading ? (
              <p className="muted">Loading your contracts…</p>
            ) : contracts.length === 0 ? (
              <p className="muted">
                No contracts yet. Upload one to check it against the 8-item checklist.
              </p>
            ) : (
              <ul className="contract-list">
                {contracts.map((c) => (
                  <li
                    key={c.id}
                    className={c.id === selectedId ? 'selected' : ''}
                    onClick={() => setSelectedId(c.id)}
                  >
                    <div className="contract-name">{c.filename}</div>
                    <div className="contract-meta">
                      {formatSize(c.size_bytes)} · {formatDate(c.created_at)}
                    </div>
                    <div className={`status status-${c.status}`}>{c.status}</div>
                    <button
                      type="button"
                      className="delete-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        onDelete(c.id)
                      }}
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="detail">
            {selected ? (
              <ContractDetail
                key={selected.id}
                contract={selected}
                getToken={getToken}
                onRefresh={refresh}
              />
            ) : (
              <p className="muted">Select a contract to see its review and chat.</p>
            )}
          </section>
        </main>
        </>
      )}
    </div>
  )
}

function ContractDetail({ contract, getToken, onRefresh }) {
  const [tab, setTab] = useState('review')
  const [live, setLive] = useState(contract)
  const [jumpChunkId, setJumpChunkId] = useState(null)

  // Poll while the backend is still processing the upload.
  useEffect(() => {
    if (live.status !== 'processing') return
    const t = setInterval(async () => {
      try {
        const fresh = await apiJson(getToken, `/api/contracts/${contract.id}`)
        setLive(fresh)
        if (fresh.status !== 'processing') {
          clearInterval(t)
          onRefresh()
        }
      } catch {
        // Transient error (e.g. backend waking from sleep, brief network
        // blip) — keep polling; the next tick retries. Stopping here used
        // to leave the UI stuck on "Processing…" even after the backend
        // had finished. Polling only ends when the status leaves
        // "processing" or this component unmounts.
      }
    }, 3000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.status, contract.id])

  function jumpToClause(chunkId) {
    setJumpChunkId(chunkId)
    setTab('text')
  }

  return (
    <div>
      <h2>{live.filename}</h2>
      <p className="muted">
        {formatSize(live.size_bytes)} · {live.page_count} page(s) · {formatDate(live.created_at)}
      </p>
      {live.status === 'processing' && <p className="notice">Processing — extracting text, embedding clauses, running the review…</p>}
      {live.review_note && <p className="notice">{live.review_note}</p>}
      {live.status === 'failed' && (
        <div className="error" role="alert">
          Review failed: {live.error || 'unknown error'}
          <button
            type="button"
            onClick={async () => {
              await apiJson(getToken, `/api/contracts/${live.id}/review/retry`, { method: 'POST' })
              setLive({ ...live, status: 'processing', error: null })
            }}
          >
            Retry review
          </button>
        </div>
      )}

      <div className="tabs">
        {['review', 'chat', 'text'].map((t) => (
          <button
            key={t}
            type="button"
            className={tab === t ? 'active' : ''}
            onClick={() => setTab(t)}
          >
            {t === 'review' ? 'Review' : t === 'chat' ? 'Ask about this contract' : 'Contract text'}
          </button>
        ))}
      </div>

      {tab === 'review' && (
        <ReviewView contract={live} getToken={getToken} onJumpToClause={jumpToClause} />
      )}
      {tab === 'chat' && <ChatPanel contract={live} getToken={getToken} onJumpToClause={jumpToClause} />}
      {tab === 'text' && (
        <ContractViewer
          contract={live}
          getToken={getToken}
          highlightChunkId={jumpChunkId}
        />
      )}
    </div>
  )
}
