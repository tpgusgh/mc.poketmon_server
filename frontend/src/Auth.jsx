import { useCallback, useEffect, useState } from 'react'

export const API_ORIGIN = 'https://players.mieung.kr'
const REFRESH_MS = 15000

export const FACTIONS = [
  { faction: 'valor', name: '발로', color: '#dc2626' },
  { faction: 'mystic', name: '미스틱', color: '#2563eb' },
  { faction: 'instinct', name: '인스팅트', color: '#eab308' },
  { faction: 'harmony', name: '하모니', color: '#ec4899' },
]

function FactionRadios({ value, onChange }) {
  return (
    <div className="faction-radios">
      {FACTIONS.map((f) => (
        <label
          key={f.faction}
          className={`faction-radio ${value === f.faction ? 'faction-radio-selected' : ''}`}
          style={{ '--faction-color': f.color }}
        >
          <input
            type="radio"
            name="faction"
            value={f.faction}
            checked={value === f.faction}
            onChange={() => onChange(f.faction)}
          />
          {f.name}
        </label>
      ))}
    </div>
  )
}

export async function apiGet(path) {
  return fetch(`${API_ORIGIN}${path}`, { credentials: 'include' })
}

export async function apiPost(path, body) {
  const res = await fetch(`${API_ORIGIN}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(json.detail || `HTTP ${res.status}`)
  }
  return json
}

export function useMe() {
  const [me, setMe] = useState(null)
  const [checked, setChecked] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const res = await apiGet('/auth/me')
      setMe(res.ok ? await res.json() : null)
    } catch {
      setMe(null)
    } finally {
      setChecked(true)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  return [me, checked, refresh]
}

export function AuthForm({ onAuthed }) {
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [playerUuid, setPlayerUuid] = useState('')
  const [faction, setFaction] = useState('')
  const [roster, setRoster] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (mode !== 'register') return
    apiGet('/players/roster').then(async (res) => {
      if (res.ok) setRoster((await res.json()).players)
    })
  }, [mode])

  const available = roster.filter((p) => !p.claimed)
  const claimed = roster.filter((p) => p.claimed)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') {
        await apiPost('/auth/login', { username, password })
      } else {
        if (!playerUuid) throw new Error('플레이어를 선택해주세요')
        if (!faction) throw new Error('진영을 선택해주세요')
        if (password !== passwordConfirm) throw new Error('비밀번호가 일치하지 않습니다')
        await apiPost('/auth/register', { username, password, player_uuid: playerUuid, faction })
      }
      await onAuthed()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const fileDispute = async (uuid) => {
    const note = window.prompt('이의제기 사유를 간단히 적어주세요 (선택)') ?? ''
    try {
      await apiPost('/disputes', { player_uuid: uuid, note })
      window.alert('이의제기가 접수되었습니다. 관리자가 확인 후 처리합니다.')
    } catch (err) {
      window.alert(err.message)
    }
  }

  return (
    <div className="auth-panel">
      <div className="auth-tabs">
        <button
          type="button"
          className={`btn ${mode === 'login' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setMode('login')}
        >
          로그인
        </button>
        <button
          type="button"
          className={`btn ${mode === 'register' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setMode('register')}
        >
          회원가입
        </button>
      </div>
      <form onSubmit={submit} className="auth-form">
        <input
          className="auth-input"
          placeholder="아이디"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          className="auth-input"
          type="password"
          placeholder="비밀번호"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {mode === 'register' && (
          <input
            className="auth-input"
            type="password"
            placeholder="비밀번호 확인"
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
          />
        )}
        {mode === 'register' && (
          <select className="auth-input" value={playerUuid} onChange={(e) => setPlayerUuid(e.target.value)}>
            <option value="">플레이어 선택...</option>
            {available.map((p) => (
              <option key={p.uuid} value={p.uuid}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        {mode === 'register' && (
          <div className="auth-faction-field">
            <p className="battle-hint">진영 선택 (한 번 선택하면 바꿀 수 없어요)</p>
            <FactionRadios value={faction} onChange={setFaction} />
          </div>
        )}
        <button className="btn btn-primary" disabled={busy} type="submit">
          {mode === 'login' ? '로그인' : '회원가입'}
        </button>
      </form>
      {error && <div className="error-banner">{error}</div>}
      {mode === 'register' && claimed.length > 0 && (
        <div className="claimed-list">
          <p className="battle-hint">이미 선택된 플레이어 (본인 계정인데 다른 사람이 선택했다면 이의제기해주세요)</p>
          <ul className="battle-list">
            {claimed.map((p) => (
              <li key={p.uuid} className="battle-row">
                <span>
                  {p.name} <span className="battle-meta">(아이디: {p.claimed_by})</span>
                </span>
                <button className="btn btn-secondary" onClick={() => fileDispute(p.uuid)}>
                  이의제기
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function ClaimPlayerForm({ onClaimed }) {
  const [roster, setRoster] = useState([])
  const [playerUuid, setPlayerUuid] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    apiGet('/players/roster').then(async (res) => {
      if (res.ok) setRoster((await res.json()).players)
    })
  }, [])

  const available = roster.filter((p) => !p.claimed)

  const submit = async (e) => {
    e.preventDefault()
    try {
      if (!playerUuid) throw new Error('플레이어를 선택해주세요')
      await apiPost('/auth/claim-player', { player_uuid: playerUuid })
      await onClaimed()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="auth-panel">
      <p className="battle-hint">이 계정의 플레이어 선택이 취소되었습니다. 본인의 플레이어를 다시 선택해주세요.</p>
      <form onSubmit={submit} className="auth-form">
        <select className="auth-input" value={playerUuid} onChange={(e) => setPlayerUuid(e.target.value)}>
          <option value="">플레이어 선택...</option>
          {available.map((p) => (
            <option key={p.uuid} value={p.uuid}>
              {p.name}
            </option>
          ))}
        </select>
        <button className="btn btn-primary" type="submit">
          선택 완료
        </button>
      </form>
      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}

export function FactionPickForm({ onPicked }) {
  const [faction, setFaction] = useState('')
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    try {
      if (!faction) throw new Error('진영을 선택해주세요')
      await apiPost('/auth/set-faction', { faction })
      await onPicked()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="auth-panel">
      <p className="battle-hint">진영을 선택해주세요. 한 번 선택하면 바꿀 수 없어요.</p>
      <form onSubmit={submit} className="auth-form">
        <FactionRadios value={faction} onChange={setFaction} />
        <button className="btn btn-primary" type="submit">
          선택 완료
        </button>
      </form>
      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}

function NotificationBell({ me }) {
  const [data, setData] = useState({ incoming: [], resolved_unseen: [], count: 0 })
  const [open, setOpen] = useState(false)

  const load = useCallback(async () => {
    const res = await apiGet('/battle/notifications')
    if (res.ok) setData(await res.json())
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (next && data.resolved_unseen.length > 0) {
      await apiPost('/battle/notifications/ack', {})
      load()
    }
  }

  const respond = async (challengeId, accept) => {
    await apiPost('/battle/respond', { challenge_id: challengeId, accept })
    load()
  }

  const hasNotifications = data.incoming.length > 0 || data.resolved_unseen.length > 0

  return (
    <div className="notif-bell">
      <button className="btn btn-secondary notif-bell-btn" onClick={toggle}>
        🔔
        {data.count > 0 && <span className="notif-badge">{data.count}</span>}
      </button>
      {open && (
        <div className="auth-dropdown notif-dropdown">
          <div className="auth-panel">
            {!hasNotifications && <p className="battle-hint">새 알림이 없어요.</p>}
            {data.incoming.map((c) => (
              <div key={c.id} className="battle-row">
                <span>{c.challenger_name}님의 배틀 신청</span>
                <div className="battle-actions">
                  <button className="btn btn-primary" onClick={() => respond(c.id, true)}>
                    수락
                  </button>
                  <button className="btn btn-secondary" onClick={() => respond(c.id, false)}>
                    거절
                  </button>
                </div>
              </div>
            ))}
            {data.resolved_unseen.map((c) => {
              const won = c.resolved_winner === me.uuid
              const opponentName = c.challenger_uuid === me.uuid ? c.opponent_name : c.challenger_name
              const delta = won ? c.winner_delta : c.loser_delta
              return (
                <div key={c.id} className="battle-row">
                  <span>
                    {won ? '🏆' : '💀'} {opponentName}와의 배틀에서 {won ? '승리' : '패배'} ({delta > 0 ? '+' : ''}
                    {delta}점)
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function AuthHeaderWidget({ me, checked, refreshMe }) {
  const [open, setOpen] = useState(false)

  const handleLogout = async () => {
    try {
      await apiPost('/auth/logout', {})
    } finally {
      await refreshMe()
    }
  }

  if (!checked) return null

  if (!me) {
    return (
      <div className="auth-header">
        <button className="btn btn-primary" onClick={() => setOpen((v) => !v)}>
          🔑 로그인 / 회원가입
        </button>
        {open && (
          <div className="auth-dropdown">
            <AuthForm
              onAuthed={async () => {
                await refreshMe()
                setOpen(false)
              }}
            />
          </div>
        )}
      </div>
    )
  }

  const factionInfo = FACTIONS.find((f) => f.faction === me.faction)

  return (
    <div className="auth-header">
      <div className="auth-header-me">
        {factionInfo && (
          <span className="faction-badge" style={{ '--faction-color': factionInfo.color }}>
            {factionInfo.name}
          </span>
        )}
        <span className="battle-me">
          <strong>{me.name}</strong>님{me.is_admin && ' (관리자)'}
        </span>
        {!me.needs_player_selection && <NotificationBell me={me} />}
        {me.needs_player_selection && (
          <button className="btn btn-secondary" onClick={() => setOpen((v) => !v)}>
            ⚠️ 플레이어 선택 필요
          </button>
        )}
        {!me.needs_player_selection && me.needs_faction_selection && (
          <button className="btn btn-secondary" onClick={() => setOpen((v) => !v)}>
            ⚠️ 진영 선택 필요
          </button>
        )}
        <button className="btn btn-secondary" onClick={handleLogout}>
          로그아웃
        </button>
      </div>
      {open && me.needs_player_selection && (
        <div className="auth-dropdown">
          <ClaimPlayerForm
            onClaimed={async () => {
              await refreshMe()
              setOpen(false)
            }}
          />
        </div>
      )}
      {open && !me.needs_player_selection && me.needs_faction_selection && (
        <div className="auth-dropdown">
          <FactionPickForm
            onPicked={async () => {
              await refreshMe()
              setOpen(false)
            }}
          />
        </div>
      )}
    </div>
  )
}
