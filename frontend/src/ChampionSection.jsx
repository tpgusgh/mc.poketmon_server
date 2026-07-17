import { useEffect, useState } from 'react'

const CHAMPION_WINS_URL = 'https://players.mieung.kr/champion-wins'
const REFRESH_MS = 15000

const MEDALS = ['🥇', '🥈', '🥉']

function formatTimestamp(iso) {
  try {
    return new Date(iso).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

export default function ChampionSection() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetch(CHAMPION_WINS_URL, { cache: 'no-store' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        if (!cancelled) setData(json)
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    }
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  if (error) return null
  if (!data || data.leaderboard.length === 0) return null

  return (
    <section className="leaderboard">
      <h2>🏆 챔피언 명예의 전당</h2>
      <ol className="board-list">
        {data.leaderboard.map((row, i) => (
          <li key={row.name} className="board-row">
            <span className="rank">{MEDALS[i] ?? `${i + 1}`}</span>
            <span className="board-name">{row.name}</span>
            <span className="board-hours">{row.wins}승</span>
          </li>
        ))}
      </ol>
      {data.recent.length > 0 && (
        <ul className="battle-list" style={{ marginTop: 16 }}>
          {data.recent.slice(0, 8).map((w, i) => (
            <li key={i} className="battle-row">
              <span>
                <strong>{w.player}</strong>님이 <strong>{w.npc}</strong>를 꺾었습니다
              </span>
              <span className="battle-meta">{formatTimestamp(w.timestamp)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
