import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from './Auth'
import { AdminAnnounce, AdminInquiries } from './Contact'
import { AdminPlayerdataBackups } from './Backups'

const REFRESH_MS = 15000

const MEDALS = ['🥇', '🥈', '🥉']

function ChallengeButton({ opponent, onChallenge }) {
  const [busy, setBusy] = useState(false)
  return (
    <button
      className="btn btn-primary"
      disabled={busy}
      onClick={async () => {
        setBusy(true)
        await onChallenge(opponent.uuid)
        setBusy(false)
      }}
    >
      배틀 신청
    </button>
  )
}

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

export default function BattleSection({ me, checked }) {
  const [onlinePlayers, setOnlinePlayers] = useState([])
  const [incoming, setIncoming] = useState([])
  const [outgoing, setOutgoing] = useState([])
  const [activeBattles, setActiveBattles] = useState([])
  const [ranking, setRanking] = useState([])
  const [disputes, setDisputes] = useState([])
  const [accountDisputes, setAccountDisputes] = useState([])
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const rankingRes = await apiGet('/battle/ranking')
      if (rankingRes.ok) setRanking((await rankingRes.json()).ranking)

      if (!me || me.needs_player_selection) return
      const [onlineRes, incomingRes, outgoingRes, activeRes] = await Promise.all([
        apiGet('/battle/online-players'),
        apiGet('/battle/incoming'),
        apiGet('/battle/outgoing'),
        apiGet('/battle/active'),
      ])
      if (onlineRes.ok) setOnlinePlayers((await onlineRes.json()).players)
      if (incomingRes.ok) setIncoming((await incomingRes.json()).challenges)
      if (outgoingRes.ok) setOutgoing((await outgoingRes.json()).challenges)
      if (activeRes.ok) setActiveBattles((await activeRes.json()).challenges)

      if (me.is_admin) {
        const [disputesRes, accountDisputesRes] = await Promise.all([
          apiGet('/admin/disputes'),
          apiGet('/admin/account-disputes'),
        ])
        if (disputesRes.ok) setDisputes((await disputesRes.json()).disputes)
        if (accountDisputesRes.ok) setAccountDisputes((await accountDisputesRes.json()).disputes)
      }
    } catch (e) {
      setError(e.message)
    }
  }, [me])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  const runAction = async (fn) => {
    try {
      await fn()
      setError(null)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  const handleChallenge = (opponentUuid) =>
    runAction(async () => {
      await apiPost('/battle/challenge', { opponent_uuid: opponentUuid })
      window.alert('배틀 신청을 보냈습니다! (1시간 내에 응답이 없으면 자동으로 만료됩니다)')
    })

  const handleCancel = (challengeId) => runAction(() => apiPost('/battle/cancel', { challenge_id: challengeId }))

  const handleRespond = (challengeId, accept) =>
    runAction(() => apiPost('/battle/respond', { challenge_id: challengeId, accept }))

  const handleReport = (challengeId, result) =>
    runAction(() => apiPost('/battle/report', { challenge_id: challengeId, result }))

  const handleAdminResolve = (challengeId, winnerUuid) =>
    runAction(() => apiPost('/admin/resolve', { challenge_id: challengeId, winner_uuid: winnerUuid }))

  const handleAdminResolveAccountDispute = (disputeId, action) =>
    runAction(() => apiPost('/admin/account-disputes/resolve', { dispute_id: disputeId, action }))

  return (
    <section className="battle">
      <h2>⚔️ 배틀</h2>

      {error && <div className="error-banner">{error}</div>}

      {!checked && <p className="battle-hint">로그인 상태 확인 중...</p>}

      {checked && !me && <p className="battle-hint">화면 상단에서 로그인/회원가입하면 배틀을 신청할 수 있어요.</p>}

      {me && me.needs_player_selection && (
        <p className="battle-hint">화면 상단에서 플레이어를 다시 선택해주세요.</p>
      )}

      {me && !me.needs_player_selection && (
        <>
          {incoming.length > 0 && (
            <div className="battle-block">
              <h3>📨 받은 배틀 신청</h3>
              <ul className="battle-list">
                {incoming.map((c) => (
                  <li key={c.id} className="battle-row">
                    <span>{c.challenger_name}님의 도전</span>
                    <div className="battle-actions">
                      <button className="btn btn-primary" onClick={() => handleRespond(c.id, true)}>
                        수락
                      </button>
                      <button className="btn btn-secondary" onClick={() => handleRespond(c.id, false)}>
                        거절
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {outgoing.length > 0 && (
            <div className="battle-block">
              <h3>📤 보낸 배틀 신청</h3>
              <ul className="battle-list">
                {outgoing.map((c) => (
                  <li key={c.id} className="battle-row">
                    <span>{c.opponent_name}님에게 신청함</span>
                    <div className="battle-actions">
                      <button className="btn btn-secondary" onClick={() => handleCancel(c.id)}>
                        취소
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {activeBattles.length > 0 && (
            <div className="battle-block">
              <h3>⏳ 진행 중인 배틀 (결과 보고)</h3>
              <ul className="battle-list">
                {activeBattles.map((c) => (
                  <li key={c.id} className="battle-row battle-row-col">
                    <span>
                      {c.challenger_name} vs {c.opponent_name}
                      {c.i_reported && <span className="battle-meta"> · 보고 완료, 상대방 응답 대기 중 (30분 내 응답 없으면 자동 처리)</span>}
                    </span>
                    {!c.i_reported && (
                      <div className="battle-actions">
                        <button className="btn btn-primary" onClick={() => handleReport(c.id, 'win')}>
                          내가 이겼다
                        </button>
                        <button className="btn btn-secondary" onClick={() => handleReport(c.id, 'lose')}>
                          내가 졌다
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="battle-block">
            <h3>🎮 배틀 신청하기</h3>
            {onlinePlayers.length > 0 ? (
              <ul className="battle-list">
                {onlinePlayers.map((p) => (
                  <li key={p.uuid} className="battle-row">
                    <span>{p.name}</span>
                    <ChallengeButton opponent={p} onChallenge={handleChallenge} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="battle-hint">지금 게임에 접속 중인 다른 플레이어가 없어요.</p>
            )}
          </div>

          {me.is_admin && <AdminDisputes disputes={disputes} onResolve={handleAdminResolve} />}
          {me.is_admin && (
            <AdminAccountDisputes disputes={accountDisputes} onResolve={handleAdminResolveAccountDispute} />
          )}
          {me.is_admin && <AdminAnnounce />}
          {me.is_admin && <AdminInquiries />}
          {me.is_admin && <AdminPlayerdataBackups />}
        </>
      )}

      <div className="battle-block">
        <h3>🏆 배틀 랭킹</h3>
        {ranking.length > 0 ? (
          <ol className="board-list">
            {ranking.map((r, i) => (
              <li key={r.uuid} className="board-row">
                <span className="rank">{MEDALS[i] ?? `${i + 1}`}</span>
                <span className={`board-name ${me && r.uuid === me.uuid ? 'board-name-self' : ''}`}>{r.name}</span>
                <span className="board-hours">{r.score}점</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="board-empty">아직 배틀 기록이 없어요.</p>
        )}
      </div>
    </section>
  )
}
