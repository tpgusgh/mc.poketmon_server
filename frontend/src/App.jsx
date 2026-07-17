import { useEffect, useState, useCallback, useRef } from 'react'
import './App.css'
import BattleSection from './BattleSection'
import GuideButton from './GuideSection'
import ChampionSection from './ChampionSection'
import FactionSection from './FactionSection'
import { useMe, AuthHeaderWidget } from './Auth'
import { ContactButton } from './Contact'
import AdminPanelButton from './AdminPanel'

const API_URL = 'https://players.mieung.kr/players'
const LEADERBOARD_URL = 'https://players.mieung.kr/leaderboard'
const STORY_URL = 'https://players.mieung.kr/story'
const LEGENDARIES_URL = 'https://players.mieung.kr/legendaries'
const PARTY_URL = 'https://players.mieung.kr/party'
const FUN_STATS_URL = 'https://players.mieung.kr/fun-stats'
const HEALTH_URL = 'https://players.mieung.kr/server-health'
const REFRESH_MS = 15000
const STORY_PAGE_SIZE = 5

const MEDALS = ['🥇', '🥈', '🥉']

const DASHBOARD_TYPES = [
  { key: 'playtime', label: '⏱️ 누적 접속시간' },
  { key: 'deaths', label: '💀 바보같은 죽음 (낙사 포함)' },
  { key: 'legendary_count', label: '🐉 전설 포켓몬 보유 수' },
  { key: 'achievements', label: '🏆 업적 달성 개수' },
]

const WEEKDAYS_KO = ['일', '월', '화', '수', '목', '금', '토']

function formatDateKo(dateStr) {
  const d = new Date(`${dateStr}T00:00:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAYS_KO[d.getDay()]})`
}

// Renders "**name**" segments as bold, without dangerouslySetInnerHTML.
function renderBold(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    return <span key={i}>{part}</span>
  })
}

function formatDuration(h) {
  if (h == null) return '알 수 없음'
  const totalMinutes = Math.round(h * 60)
  const days = Math.floor(totalMinutes / (60 * 24))
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days}일 ${hours}시간 ${minutes}분`
  if (hours > 0) return `${hours}시간 ${minutes}분`
  return `${minutes}분`
}

function PokeballLogo() {
  return (
    <svg className="pokeball-logo" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="29" fill="#fff" stroke="#1a1a1a" strokeWidth="3.5" />
      <path d="M3 32a29 29 0 0 1 58 0z" fill="#ee1515" stroke="#1a1a1a" strokeWidth="3.5" />
      <rect x="3" y="29" width="58" height="6" fill="#1a1a1a" />
      <circle cx="32" cy="32" r="9" fill="#fff" stroke="#1a1a1a" strokeWidth="4" />
      <circle cx="32" cy="32" r="4" fill="#fff" stroke="#1a1a1a" strokeWidth="2" />
    </svg>
  )
}

function HpBar({ hp, maxHp, fainted }) {
  const ratio = maxHp > 0 ? Math.max(0, Math.min(1, hp / maxHp)) : 0
  const level = fainted ? 'fainted' : ratio > 0.5 ? 'good' : ratio > 0.2 ? 'warning' : 'critical'
  return (
    <div className="hp-row">
      <div className={`hp-track hp-${level}`}>
        <div className="hp-fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      <span className="hp-text">{fainted ? '기절' : `${hp}/${maxHp}`}</span>
    </div>
  )
}

function PlayerCard({ player }) {
  const isOnline = player.status === 'online'
  return (
    <div className={`card ${isOnline ? 'card-online' : 'card-offline'}`}>
      <div className="card-top">
        <span className="name">{player.name}</span>
        <span className={`badge ${isOnline ? 'badge-good' : 'badge-muted'}`}>
          <span className="dot" aria-hidden="true" />
          {isOnline ? '온라인' : '오프라인'}
        </span>
      </div>
      <div className="card-body">
        {isOnline ? (
          <>
            <span className="value">{formatDuration(player.hours_connected)}</span>
            <span className="label">째 접속 중</span>
          </>
        ) : (
          <>
            <span className="value">{formatDuration(player.hours_since_last_seen)}</span>
            <span className="label">전 마지막 접속</span>
          </>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || '')
  const [me, checked, refreshMe] = useMe()
  const [data, setData] = useState(null)
  const [leaderboard, setLeaderboard] = useState(null)
  const [story, setStory] = useState(null)
  const [legendaries, setLegendaries] = useState(null)
  const [party, setParty] = useState(null)
  const [funStats, setFunStats] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [selectedDate, setSelectedDate] = useState('all')
  const [dashboardType, setDashboardType] = useState('playtime')
  const [visibleDayCount, setVisibleDayCount] = useState(STORY_PAGE_SIZE)
  const storySentinelRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const [statusRes, boardRes, storyRes, legendRes, partyRes, funRes, healthRes] = await Promise.all([
        fetch(API_URL, { cache: 'no-store' }),
        fetch(LEADERBOARD_URL, { cache: 'no-store' }),
        fetch(STORY_URL, { cache: 'no-store' }),
        fetch(LEGENDARIES_URL, { cache: 'no-store' }),
        fetch(PARTY_URL, { cache: 'no-store' }),
        fetch(FUN_STATS_URL, { cache: 'no-store' }),
        fetch(HEALTH_URL, { cache: 'no-store' }),
      ])
      if (!statusRes.ok) throw new Error(`HTTP ${statusRes.status}`)
      if (!boardRes.ok) throw new Error(`HTTP ${boardRes.status}`)
      if (!storyRes.ok) throw new Error(`HTTP ${storyRes.status}`)
      if (!legendRes.ok) throw new Error(`HTTP ${legendRes.status}`)
      if (!partyRes.ok) throw new Error(`HTTP ${partyRes.status}`)
      if (!funRes.ok) throw new Error(`HTTP ${funRes.status}`)
      if (!healthRes.ok) throw new Error(`HTTP ${healthRes.status}`)
      const json = await statusRes.json()
      const boardJson = await boardRes.json()
      const storyJson = await storyRes.json()
      const legendJson = await legendRes.json()
      const partyJson = await partyRes.json()
      const funJson = await funRes.json()
      const healthJson = await healthRes.json()
      setData(json)
      setLeaderboard(boardJson.leaderboard)
      setStory(storyJson.story)
      setLegendaries(legendJson.players)
      setParty(partyJson.players)
      setFunStats(funJson)
      setHealth(healthJson)
      setError(null)
      setLastUpdated(new Date())
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  useEffect(() => {
    if (theme) localStorage.setItem('theme', theme)
    else localStorage.removeItem('theme')
  }, [theme])

  const toggleTheme = () => {
    setTheme((t) => {
      if (t === 'dark') return 'light'
      if (t === 'light') return 'dark'
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      return prefersDark ? 'light' : 'dark'
    })
  }

  useEffect(() => {
    setVisibleDayCount(STORY_PAGE_SIZE)
  }, [selectedDate])

  useEffect(() => {
    const el = storySentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setVisibleDayCount((n) => n + STORY_PAGE_SIZE)
        }
      },
      { rootMargin: '200px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [story, selectedDate])

  const onlineCount = data?.players?.filter((p) => p.status === 'online').length ?? 0
  const totalCount = data?.players?.length ?? 0

  const DASHBOARD_UNIT = { deaths: '회', legendary_count: '마리', achievements: '개' }

  const dashboardRows =
    dashboardType === 'playtime'
      ? (leaderboard ?? []).map((p) => ({
          name: p.name,
          online: p.online,
          valueText: formatDuration(p.total_hours),
        }))
      : (funStats?.[dashboardType]?.rows ?? []).map((r) => ({
          name: r.name,
          online: data?.players?.some((p) => p.name === r.name && p.status === 'online'),
          valueText: `${r.value}${DASHBOARD_UNIT[dashboardType] ?? ''}`,
        }))

  const effectiveTheme = theme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')

  return (
    <div className="page" data-theme={theme || undefined}>
      <header className="header">
        <div className="brand">
          <PokeballLogo />
          <h1>포켓몬 서버 접속 현황</h1>
        </div>
        <div className="header-right">
          <div className={`server-status ${data?.server_online ? 'badge-good' : 'badge-critical'}`}>
            <span className="dot" aria-hidden="true" />
            {data ? (data.server_online ? '서버 가동 중' : '서버 꺼짐') : '불러오는 중...'}
          </div>
          <button
            className="btn btn-secondary theme-toggle-btn"
            onClick={toggleTheme}
            aria-label="라이트/다크 모드 전환"
            title="라이트/다크 모드 전환"
          >
            {effectiveTheme === 'dark' ? '☀️' : '🌙'}
          </button>
          <GuideButton />
          <ContactButton me={me} />
          <AdminPanelButton me={me} />
          <AuthHeaderWidget me={me} checked={checked} refreshMe={refreshMe} />
        </div>
      </header>

      {error && (
        <div className="error-banner">
          데이터를 불러오지 못했습니다: {error}
        </div>
      )}

      {data && (
        <p className="summary">
          현재 온라인 <strong>{onlineCount}</strong> / 전체 {totalCount}명
        </p>
      )}

      {health && (
        <div className="health-row">
          <span className={`badge badge-${health.cpu.status}`}>
            CPU 부하 {Math.round(health.cpu.ratio * 100)}% (load {health.cpu.load1} / {health.cpu.cores}코어)
          </span>
          <span className={`badge badge-${health.memory.status}`}>
            메모리 {health.memory.used_gb}GB / {health.memory.total_gb}GB ({Math.round(health.memory.ratio * 100)}%)
          </span>
          {health.minecraft_memory_gb != null && (
            <span className="badge badge-muted">서버1 JVM {health.minecraft_memory_gb}GB</span>
          )}
        </div>
      )}

      <div className="grid">
        {data?.players?.map((p) => (
          <PlayerCard key={p.name} player={p} />
        ))}
      </div>

      {leaderboard && (
        <section className="leaderboard">
          <div className="story-head-row">
            <h2>대시보드</h2>
            <select
              className="date-select"
              value={dashboardType}
              onChange={(e) => setDashboardType(e.target.value)}
            >
              {DASHBOARD_TYPES.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          {dashboardRows.length > 0 ? (
            <ol className="board-list">
              {dashboardRows.map((row, i) => (
                <li key={row.name} className="board-row">
                  <span className="rank">{MEDALS[i] ?? `${i + 1}`}</span>
                  <span className="board-name">
                    {row.name}
                    {row.online && <span className="online-dot" aria-label="온라인" title="온라인" />}
                  </span>
                  <span className="board-hours">{row.valueText}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="board-empty">아직 기록이 없어요.</p>
          )}
        </section>
      )}

      {party && party.length > 0 && (
        <section className="legendaries">
          <h2>플레이어별 파티 포켓몬</h2>
          <div className="legend-grid">
            {party.map((p) => (
              <div key={p.name} className="legend-card">
                <div className="legend-owner" style={p.faction_color ? { color: p.faction_color } : undefined}>
                  {p.name}
                  {p.faction_name && <span className="legend-owner-faction">{p.faction_name}</span>}
                </div>
                <ul className="party-list">
                  {p.party.map((mon, i) => (
                    <li key={i} className="party-item">
                      <div className="party-item-top">
                        <span className="legend-species">{mon.species}</span>
                        <span className="legend-meta">Lv.{mon.level}</span>
                      </div>
                      <HpBar hp={mon.hp} maxHp={mon.max_hp} fainted={mon.fainted} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      {legendaries && legendaries.length > 0 && (
        <section className="legendaries">
          <h2>플레이어별 전설의 포켓몬</h2>
          <div className="legend-grid">
            {legendaries.map((p) => (
              <div key={p.name} className="legend-card">
                <div className="legend-owner">{p.name}</div>
                <ul className="legend-list">
                  {p.legendaries.map((mon, i) => (
                    <li key={i} className="legend-item">
                      <span className="legend-species">{mon.species}</span>
                      <span className="legend-meta">
                        Lv.{mon.level} · {mon.ball}
                        {mon.location === 'pc' && <span className="legend-pc-tag">PC</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      <FactionSection />

      <BattleSection me={me} checked={checked} />

      <ChampionSection />

      {story && story.length > 0 && (() => {
        const filteredDays = [...story].reverse().filter((day) => selectedDate === 'all' || day.date === selectedDate)
        const visibleDays = selectedDate === 'all' ? filteredDays.slice(0, visibleDayCount) : filteredDays
        const hasMore = selectedDate === 'all' && visibleDayCount < filteredDays.length
        return (
          <section className="story">
            <div className="story-head-row">
              <h2>서버 스토리</h2>
              <select
                className="date-select"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
              >
                <option value="all">전체 날짜</option>
                {[...story].reverse().map((day) => (
                  <option key={day.date} value={day.date}>
                    {formatDateKo(day.date)}
                  </option>
                ))}
              </select>
            </div>
            {visibleDays.map((day) => (
              <div key={day.date} className="story-day">
                <div className="story-day-head">
                  <h3>{formatDateKo(day.date)}</h3>
                  {day.headline && <span className="story-headline">{day.headline}</span>}
                </div>
                <ul className="story-events">
                  {day.events.map((event, i) => (
                    <li key={i}>{renderBold(event)}</li>
                  ))}
                </ul>
              </div>
            ))}
            {hasMore && (
              <div ref={storySentinelRef} className="story-load-sentinel">
                <span className="battle-hint">스크롤하면 더 불러옵니다...</span>
              </div>
            )}
          </section>
        )
      })()}

      {lastUpdated && (
        <footer className="footer">
          마지막 갱신: {lastUpdated.toLocaleTimeString('ko-KR')} · 15초마다 자동 갱신
        </footer>
      )}
    </div>
  )
}
