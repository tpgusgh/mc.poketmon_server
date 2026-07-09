import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from './Auth'
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

export default function AdminPanelButton({ me }) {
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
            <AdminDisputes disputes={disputes} onResolve={handleAdminResolve} />
            <AdminAccountDisputes disputes={accountDisputes} onResolve={handleAdminResolveAccountDispute} />
            <AdminAnnounce />
            <AdminInquiries />
            <AdminPlayerdataBackups />
          </div>
        </div>
      )}
    </>
  )
}
