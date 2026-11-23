import { useEffect, useRef, useState } from 'react'
import { apiJson, streamChat } from '../api.js'

// Follow-up chat. Answers stream in as they are generated; verified
// sources (quotes checked against the contract) render under each answer.
export default function ChatPanel({ contract, getToken, onJumpToClause }) {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef(null)

  useEffect(() => {
    apiJson(getToken, `/api/contracts/${contract.id}/chat`)
      .then(setMessages)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contract.id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const question = input.trim()
    if (!question || sending) return
    setInput('')
    setSending(true)
    setError('')
    const userMsg = { id: `local-${Date.now()}`, role: 'user', content: question, sources: [] }
    const assistantId = `local-${Date.now()}-a`
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '', sources: [] },
    ])
    try {
      await streamChat(getToken, contract.id, question, (event) => {
        if (event.type === 'token') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + event.text } : m,
            ),
          )
        } else if (event.type === 'done') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, sources: event.sources || [] } : m,
            ),
          )
        } else if (event.type === 'error') {
          setError(event.text)
        }
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  if (loading) return <p className="muted">Loading chat history…</p>

  return (
    <div className="chat">
      {error && (
        <div className="error" role="alert">
          {error}
          <button type="button" onClick={() => setError('')}>
            Dismiss
          </button>
        </div>
      )}
      {messages.length === 0 && (
        <p className="muted">
          Ask anything about this contract — answers come only from the contract text, with
          the clause quoted. Try “What happens if either side wants to end this contract?”
        </p>
      )}
      <ul className="chat-list">
        {messages.map((m) => (
          <li key={m.id} className={`chat-msg chat-${m.role}`}>
            <div className="chat-role">{m.role === 'user' ? 'You' : 'Assistant'}</div>
            <div className="chat-text">{m.content || '…'}</div>
            {m.role === 'assistant' && m.sources && m.sources.length > 0 && (
              <div className="chat-sources">
                <strong>Sources</strong>
                {m.sources.map((s, i) => (
                  <blockquote
                    key={i}
                    className="quote"
                    title="Click to see the full clause in the contract"
                    onClick={() => s.chunk_id && onJumpToClause(s.chunk_id)}
                  >
                    “{s.quote}”
                    <footer>
                      {s.page ? `page ${s.page}` : 'page unknown'}
                      {s.verified ? '' : ' · quote could not be verified'}
                      {s.chunk_id && ' · click to see the full clause'}
                    </footer>
                  </blockquote>
                ))}
              </div>
            )}
          </li>
        ))}
        <li ref={bottomRef} />
      </ul>
      <div className="chat-input">
        <input
          type="text"
          value={input}
          placeholder="Ask about this contract…"
          disabled={sending}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') send()
          }}
        />
        <button type="button" onClick={send} disabled={sending || !input.trim()}>
          {sending ? 'Answering…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
