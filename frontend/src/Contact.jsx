import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from './Auth'

const REFRESH_MS = 15000

export function ContactButton({ me }) {
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState(null)
  const [sent, setSent] = useState(false)

  const toggle = () => {
    setOpen((v) => !v)
    setSent(false)
    setError(null)
  }

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      if (!message.trim()) throw new Error('문의 내용을 입력해주세요')
      await apiPost('/contact', { message })
      setSent(true)
      setMessage('')
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="auth-header">
      <button className="btn btn-secondary" onClick={toggle}>
        ✉️ 문의하기
      </button>
      {open && (
        <div className="auth-dropdown">
          <div className="auth-panel">
            {!me ? (
              <p className="battle-hint">문의하려면 화면 상단에서 먼저 로그인해주세요.</p>
            ) : sent ? (
              <p className="battle-hint">문의가 접수되었습니다. 감사합니다!</p>
            ) : (
              <form onSubmit={submit} className="auth-form">
                <textarea
                  className="auth-input contact-textarea"
                  placeholder="문의 내용을 입력해주세요"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={4}
                />
                <button className="btn btn-primary" type="submit">
                  보내기
                </button>
              </form>
            )}
            {error && <div className="error-banner">{error}</div>}
          </div>
        </div>
      )}
    </div>
  )
}

export function AdminAnnounce() {
  const [message, setMessage] = useState('')
  const [error, setError] = useState(null)
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setSent(false)
    setBusy(true)
    try {
      if (!message.trim()) throw new Error('공지 내용을 입력해주세요')
      await apiPost('/admin/announce', { message })
      setSent(true)
      setMessage('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="battle-block admin-block">
      <h3>📢 게임 내 공지</h3>
      <p className="battle-meta">지금 접속 중인 모든 플레이어의 채팅창에 바로 표시됩니다.</p>
      <form onSubmit={submit} className="auth-form">
        <textarea
          className="auth-input contact-textarea"
          placeholder="공지 내용을 입력해주세요"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
        />
        <button className="btn btn-primary" disabled={busy} type="submit">
          보내기
        </button>
      </form>
      {sent && <p className="battle-hint">공지를 보냈습니다.</p>}
      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}

export function AdminInquiries() {
  const [inquiries, setInquiries] = useState([])

  const load = useCallback(async () => {
    const res = await apiGet('/admin/inquiries')
    if (res.ok) setInquiries((await res.json()).inquiries)
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  const resolve = async (id) => {
    await apiPost('/admin/inquiries/resolve', { inquiry_id: id })
    load()
  }

  const open = inquiries.filter((i) => i.status === 'open')
  if (open.length === 0) return null

  return (
    <div className="battle-block admin-block">
      <h3>✉️ 문의함</h3>
      <ul className="battle-list">
        {open.map((i) => (
          <li key={i.id} className="battle-row battle-row-col">
            <div className="battle-vs">
              <strong>{i.player_name}</strong>
            </div>
            <div className="battle-meta">{i.message}</div>
            <div className="battle-actions">
              <button className="btn btn-secondary" onClick={() => resolve(i.id)}>
                처리 완료
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
