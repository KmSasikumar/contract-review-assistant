// All API calls carry the Clerk session token. The backend verifies it
// and scopes every query to that user — the frontend never sends a user id.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function apiJson(getToken, path, opts = {}) {
  const token = await getToken()
  const res = await fetch(`${API_URL}${path}`, {
    ...opts,
    headers: {
      ...(opts.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  })
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body.detail) msg = body.detail
    } catch {
      /* keep the default message */
    }
    throw new Error(msg)
  }
  if (res.status === 204) return null
  return res.json()
}

export async function uploadContract(getToken, file) {
  const token = await getToken()
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_URL}/api/contracts`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) {
    let msg = `Upload failed (${res.status})`
    try {
      const body = await res.json()
      if (body.detail) msg = body.detail
    } catch {
      /* keep the default message */
    }
    throw new Error(msg)
  }
  return res.json()
}

// Streaming chat: calls onEvent for each SSE event {type, text?, sources?}.
export async function streamChat(getToken, contractId, question, onEvent) {
  const token = await getToken()
  const res = await fetch(`${API_URL}/api/contracts/${contractId}/chat`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) {
    let msg = `Chat failed (${res.status})`
    try {
      const body = await res.json()
      if (body.detail) msg = body.detail
    } catch {
      /* keep the default message */
    }
    throw new Error(msg)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = raw.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      try {
        onEvent(JSON.parse(line.slice(5).trim()))
      } catch {
        /* ignore a malformed event */
      }
    }
  }
}

export async function getHealth() {
  const res = await fetch(`${API_URL}/api/health`)
  if (!res.ok) return { ok: false, ai_configured: false, auth_configured: false }
  return res.json()
}
