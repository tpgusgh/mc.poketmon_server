import { useCallback, useEffect, useState } from 'react'
import { apiGet } from './Auth'

const REFRESH_MS = 15000

export default function FactionSection() {
  const [ranking, setRanking] = useState([])
  const [boosted, setBoosted] = useState([])

  const load = useCallback(async () => {
    const res = await apiGet('/factions/ranking')
    if (res.ok) {
      const json = await res.json()
      setRanking(json.ranking)
      setBoosted(json.boosted)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  return (
    <section className="faction-section">
      <h2>🚩 진영전</h2>
      <p className="battle-hint">
        회원가입할 때 고른 발로/미스틱/인스팅트/하모니 진영별로, 소속 플레이어들의 배틀 랭킹 점수 평균을 매겨서
        순위를 매깁니다. 실제 게임 안에서 <strong>1등 진영은 경험치 1.5배</strong>, <strong>2등 진영은 1.2배</strong>를
        받습니다 (서버에 설치된 전용 모드가 실시간으로 적용 — 아이템이 아니라 진짜 배수 적용). 순위는 배틀 결과에
        따라 계속 바뀌니, 내 진영 순위를 지키려면 배틀에서 이겨보세요!
      </p>
      <ul className="faction-list">
        {ranking.map((r, i) => {
          const boost = boosted.find((b) => b.faction === r.faction)
          return (
            <li key={r.faction} className="faction-row" style={{ '--faction-color': r.color }}>
              <span className="faction-rank">{i + 1}</span>
              <span className="faction-name-dot" />
              <span className="faction-row-name">{r.name}</span>
              <span className="faction-row-meta">{r.member_count}명</span>
              <span className="faction-row-score">평균 {r.avg_score}점</span>
              {boost && <span className="faction-boost-badge">⚡ 경험치 {boost.multiplier}배</span>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
