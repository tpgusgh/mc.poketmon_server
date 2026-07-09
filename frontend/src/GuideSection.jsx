import { useEffect, useState } from 'react'

const MODS = [
  { name: 'Pixelmon', version: '9.1.13' },
  { name: "Xaero's Minimap", version: '' },
  { name: "Xaero's World Map", version: '' },
  { name: 'XaeroLib', version: '' },
  { name: "Nature's Compass", version: '1.9.1' },
  { name: "Explorer's Compass", version: '1.1.2' },
]

function GuideContent() {
  return (
    <>
      <div className="guide-grid">
        <div className="guide-card">
          <h3>1. 준비물</h3>
          <p className="guide-sub">
            마인크래프트 <strong>1.16.5</strong> + Forge <strong>36.2.34</strong> + 아래 모드를 설치해야 접속됩니다.
          </p>
          <ul className="guide-mod-list">
            {MODS.map((m) => (
              <li key={m.name}>
                <span>{m.name}</span>
                {m.version && <span className="guide-mod-version">{m.version}</span>}
              </li>
            ))}
          </ul>
        </div>

        <div className="guide-card">
          <h3>2. 서버 주소</h3>
          <p className="guide-address">mc.mieung.kr</p>
          <p className="guide-sub">포트 번호는 안 붙여도 됩니다 (자동 연결).</p>
        </div>

        <div className="guide-card">
          <h3>3. 자동 재시작</h3>
          <p className="guide-sub">
            매일 <strong>새벽 6시</strong>에 서버가 자동으로 재시작됩니다. 이 시간에는 잠시 접속이 끊길 수 있어요.
          </p>
        </div>

        <div className="guide-card guide-rules">
          <h3>4. 규칙</h3>
          <ul className="guide-rule-list">
            <li>
              <span className="guide-rule-no">🚫 집 털기 금지</span>
              다른 사람의 집/기지를 부수거나 몰래 아이템을 가져가는 행위는 금지입니다.
            </li>
            <li>
              <span className="guide-rule-ok">✅ 약탈 조건부 허용</span>
              상대가 <strong>몬스터에게 죽거나 사고사 등으로 자연스럽게 사망</strong>해서 떨어진 아이템을 줍는 건 괜찮습니다.
              다만 <strong>상대를 의도적으로 죽이고(PK) 나서 약탈</strong>하는 건 금지입니다.
            </li>
          </ul>
        </div>
      </div>
    </>
  )
}

export default function GuideButton() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <>
      <button className="btn btn-primary" onClick={() => setOpen(true)}>
        🎮 접속 방법
      </button>
      {open && (
        <div className="guide-modal-overlay" onClick={() => setOpen(false)}>
          <div className="guide-modal" onClick={(e) => e.stopPropagation()}>
            <div className="guide-modal-head">
              <h2>🎮 접속 가이드</h2>
              <button className="btn btn-secondary" onClick={() => setOpen(false)}>
                닫기
              </button>
            </div>
            <GuideContent />
          </div>
        </div>
      )}
    </>
  )
}
