import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, FACTIONS } from './Auth'
import { AdminAnnounce, AdminInquiries } from './Contact'
import { AdminPlayerdataBackups } from './Backups'

const REFRESH_MS = 15000

const DISPUTE_REASON_LABEL = {
  mismatch: '두 사람의 보고 내용이 서로 달라요',
  no_reports: '30분이 지나도록 아무도 보고하지 않았어요',
}

function AdminDisputes({ disputes, onResolve }) {
  if (disputes.length === 0) return null
  return (
    <div className="battle-block admin-block">
      <h3>🛠️ 판정 대기 (분쟁)</h3>
      <ul className="battle-list">
        {disputes.map((d) => (
          <li key={d.id} className="battle-row battle-row-col">
            <div className="battle-vs">
              <strong>{d.challenger_name}</strong> vs <strong>{d.opponent_name}</strong>
            </div>
            <div className="battle-meta">{DISPUTE_REASON_LABEL[d.dispute_reason] ?? '판정이 필요해요'}</div>
            <div className="battle-actions">
              <button className="btn btn-secondary" onClick={() => onResolve(d.id, d.challenger_uuid)}>
                {d.challenger_name} 승리로 확정
              </button>
              <button className="btn btn-secondary" onClick={() => onResolve(d.id, d.opponent_uuid)}>
                {d.opponent_name} 승리로 확정
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AdminAccountDisputes({ disputes, onResolve }) {
  if (disputes.length === 0) return null
  return (
    <div className="battle-block admin-block">
      <h3>🧾 계정 이의제기</h3>
      <ul className="battle-list">
        {disputes.map((d) => (
          <li key={d.id} className="battle-row battle-row-col">
            <div className="battle-vs">
              <strong>{d.player_name}</strong> — 현재 아이디 <strong>{d.claimed_by_username}</strong>가 선택 중
            </div>
            {d.note && <div className="battle-meta">사유: {d.note}</div>}
            <div className="battle-actions">
              <button className="btn btn-secondary" onClick={() => onResolve(d.id, 'remove_claim')}>
                선택 삭제 (되돌리기)
              </button>
              <button className="btn btn-secondary" onClick={() => onResolve(d.id, 'dismiss')}>
                문제 없음 (기각)
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AdminForceFaction({ players, onChange }) {
  const [selected, setSelected] = useState({})

  if (players.length === 0) return null

  return (
    <div className="battle-block admin-block">
      <h3>🚩 플레이어 진영 강제 변경</h3>
      <ul className="battle-list">
        {players.map((p) => {
          const current = FACTIONS.find((f) => f.faction === p.faction)
          const pick = selected[p.uuid] ?? p.faction ?? FACTIONS[0].faction
          return (
            <li key={p.uuid} className="battle-row">
              <span>
                <strong>{p.name}</strong>
                {current ? (
                  <span className="faction-badge" style={{ '--faction-color': current.color, marginLeft: 8 }}>
                    {current.name}
                  </span>
                ) : (
                  <span className="faction-badge" style={{ '--faction-color': '#999', marginLeft: 8 }}>
                    미배정
                  </span>
                )}
              </span>
              <div className="battle-actions">
                <select
                  className="date-select"
                  value={pick}
                  onChange={(e) => setSelected((s) => ({ ...s, [p.uuid]: e.target.value }))}
                >
                  {FACTIONS.map((f) => (
                    <option key={f.faction} value={f.faction}>
                      {f.name}
                    </option>
                  ))}
                </select>
                <button
                  className="btn btn-secondary"
                  disabled={pick === p.faction}
                  onClick={() => onChange(p.uuid, pick)}
                >
                  변경
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function AdminBans({ players, onBan, onUnban }) {
  const [reasons, setReasons] = useState({})

  if (players.length === 0) return null

  return (
    <div className="battle-block admin-block">
      <h3>⛔ 플레이어 밴 관리</h3>
      <ul className="battle-list">
        {players.map((p) => (
          <li key={p.uuid} className="battle-row battle-row-col">
            <span>
              <strong>{p.name}</strong>
              {p.banned && (
                <span className="faction-badge" style={{ '--faction-color': '#dc2626', marginLeft: 8 }}>
                  밴됨{p.reason ? ` (${p.reason})` : ''}
                </span>
              )}
            </span>
            <div className="battle-actions">
              {p.banned ? (
                <button className="btn btn-secondary" onClick={() => onUnban(p.uuid)}>
                  밴 해제
                </button>
              ) : (
                <>
                  <input
                    type="text"
                    className="date-select"
                    placeholder="사유 (선택)"
                    value={reasons[p.uuid] ?? ''}
                    onChange={(e) => setReasons((r) => ({ ...r, [p.uuid]: e.target.value }))}
                  />
                  <button className="btn btn-secondary" onClick={() => onBan(p.uuid, reasons[p.uuid] ?? '')}>
                    밴
                  </button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Things that need an admin decision: battle disputes, account-claim
 * disputes, and player inquiries -- kept separate from the general admin
 * toolkit below so they're quick to check without wading through
 * announce/backup/faction tools. */
export function AdminInboxButton({ me }) {
  const [open, setOpen] = useState(false)
  const [disputes, setDisputes] = useState([])
  const [accountDisputes, setAccountDisputes] = useState([])
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const [disputesRes, accountDisputesRes] = await Promise.all([
        apiGet('/admin/disputes'),
        apiGet('/admin/account-disputes'),
      ])
      if (disputesRes.ok) setDisputes((await disputesRes.json()).disputes)
      if (accountDisputesRes.ok) setAccountDisputes((await accountDisputesRes.json()).disputes)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [open, load])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  const runAction = async (fn) => {
    try {
      await fn()
      setError(null)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  const handleAdminResolve = (challengeId, winnerUuid) =>
    runAction(() => apiPost('/admin/resolve', { challenge_id: challengeId, winner_uuid: winnerUuid }))

  const handleAdminResolveAccountDispute = (disputeId, action) =>
    runAction(() => apiPost('/admin/account-disputes/resolve', { dispute_id: disputeId, action }))

  if (!me?.is_admin) return null

  return (
    <>
      <button className="btn btn-secondary" onClick={() => setOpen(true)}>
        📋 처리함
      </button>
      {open && (
        <div className="guide-modal-overlay" onClick={() => setOpen(false)}>
          <div className="guide-modal" onClick={(e) => e.stopPropagation()}>
            <div className="guide-modal-head">
              <h2>📋 관리자 처리함</h2>
              <button className="btn btn-secondary" onClick={() => setOpen(false)}>
                닫기
              </button>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <AdminDisputes disputes={disputes} onResolve={handleAdminResolve} />
            <AdminAccountDisputes disputes={accountDisputes} onResolve={handleAdminResolveAccountDispute} />
            <AdminInquiries />
          </div>
        </div>
      )}
    </>
  )
}

export default function AdminPanelButton({ me }) {
  const [open, setOpen] = useState(false)
  const [factionPlayers, setFactionPlayers] = useState([])
  const [bannablePlayers, setBannablePlayers] = useState([])
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const [factionPlayersRes, bannedRes] = await Promise.all([
        apiGet('/admin/players-factions'),
        apiGet('/admin/banned-players'),
      ])
      if (factionPlayersRes.ok) setFactionPlayers((await factionPlayersRes.json()).players)
      if (bannedRes.ok) setBannablePlayers((await bannedRes.json()).players)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [open, load])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  const runAction = async (fn) => {
    try {
      await fn()
      setError(null)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  const handleForceFaction = (playerUuid, faction) =>
    runAction(() => apiPost('/admin/set-player-faction', { player_uuid: playerUuid, faction }))

  const handleBan = (playerUuid, reason) =>
    runAction(() => apiPost('/admin/ban', { player_uuid: playerUuid, reason }))

  const handleUnban = (playerUuid) =>
    runAction(() => apiPost('/admin/unban', { player_uuid: playerUuid }))

  if (!me?.is_admin) return null

  return (
    <>
      <button className="btn btn-secondary" onClick={() => setOpen(true)}>
        🛠️ 관리자
      </button>
      {open && (
        <div className="guide-modal-overlay" onClick={() => setOpen(false)}>
          <div className="guide-modal" onClick={(e) => e.stopPropagation()}>
            <div className="guide-modal-head">
              <h2>🛠️ 관리자 페이지</h2>
              <button className="btn btn-secondary" onClick={() => setOpen(false)}>
                닫기
              </button>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <AdminForceFaction players={factionPlayers} onChange={handleForceFaction} />
            <AdminBans players={bannablePlayers} onBan={handleBan} onUnban={handleUnban} />
            <AdminAnnounce />
            <AdminPlayerdataBackups />
          </div>
        </div>
      )}
    </>
  )
}
