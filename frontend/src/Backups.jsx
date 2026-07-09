import { useEffect, useState } from 'react'
import { apiGet, apiPost } from './Auth'

function formatSnapshotLabel(snapshot) {
  // "2026-07-09T20-26-03" -> "2026-07-09 20:26:03"
  const [datePart, timePart] = snapshot.split('T')
  if (!timePart) return snapshot
  return `${datePart} ${timePart.replace(/-/g, ':')}`
}

export function AdminPlayerdataBackups() {
  const [snapshots, setSnapshots] = useState([])
  const [selectedSnapshot, setSelectedSnapshot] = useState('')
  const [players, setPlayers] = useState([])
  const [selectedUuid, setSelectedUuid] = useState('')
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  useEffect(() => {
    apiGet('/admin/playerdata-backups').then(async (res) => {
      if (res.ok) setSnapshots((await res.json()).snapshots)
    })
  }, [])

  useEffect(() => {
    setPlayers([])
    setSelectedUuid('')
    if (!selectedSnapshot) return
    apiGet(`/admin/playerdata-backups/${selectedSnapshot}/players`).then(async (res) => {
      if (res.ok) setPlayers((await res.json()).players)
    })
  }, [selectedSnapshot])

  const restore = async () => {
    setError(null)
    setDone(null)
    try {
      if (!selectedSnapshot || !selectedUuid) throw new Error('스냅샷과 플레이어를 선택해주세요')
      await apiPost('/admin/playerdata-backups/restore', {
        snapshot: selectedSnapshot,
        player_uuid: selectedUuid,
      })
      setDone('복구되었습니다. 해당 플레이어가 다음 접속 시 복구된 아이템을 보게 됩니다.')
    } catch (err) {
      setError(err.message)
    }
  }

  const selectedPlayer = players.find((p) => p.uuid === selectedUuid)

  return (
    <div className="battle-block admin-block">
      <h3>🎒 아이템 백업 복구</h3>
      <p className="battle-meta">
        서버가 재시작될 때마다(매일 새벽 6시) 전체 플레이어의 인벤토리를 스냅샷으로 저장해둡니다 (최근 7개 보관).
        공허 낙사 등으로 아이템을 잃어버렸을 때, 재시작 시점 상태로 되돌릴 수 있습니다. 대상 플레이어가
        <strong> 접속 중이 아닐 때만</strong> 복구할 수 있어요.
      </p>
      <form className="auth-form" onSubmit={(e) => e.preventDefault()}>
        <select className="auth-input" value={selectedSnapshot} onChange={(e) => setSelectedSnapshot(e.target.value)}>
          <option value="">스냅샷 선택...</option>
          {snapshots.map((s) => (
            <option key={s} value={s}>
              {formatSnapshotLabel(s)}
            </option>
          ))}
        </select>
        <select
          className="auth-input"
          value={selectedUuid}
          onChange={(e) => setSelectedUuid(e.target.value)}
          disabled={!selectedSnapshot}
        >
          <option value="">플레이어 선택...</option>
          {players.map((p) => (
            <option key={p.uuid} value={p.uuid}>
              {p.name}
              {p.online ? ' (접속 중)' : ''}
            </option>
          ))}
        </select>
        <button className="btn btn-primary" onClick={restore} disabled={!selectedUuid || selectedPlayer?.online}>
          이 스냅샷으로 복구
        </button>
      </form>
      {selectedPlayer?.online && (
        <p className="battle-hint">이 플레이어는 지금 접속 중이라 복구할 수 없어요. 접속 종료 후 다시 시도해주세요.</p>
      )}
      {done && <p className="battle-hint">{done}</p>}
      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}
