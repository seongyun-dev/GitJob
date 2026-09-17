import type { ReactNode } from 'react'

/**
 * 화면 상단 Hero · 티켓 S15P21E102-192.
 *
 * `GitJob Desktop UI Final.html`의 모든 로그인 이후 섹션이 같은 골격을 쓴다.
 * eyebrow → 큰 제목 → 설명. 치수는 `section#repos`에서 읽은 값이다.
 *   eyebrow 11px / weight 800 / letter-spacing 1.76px / #2F5EEB
 *   제목     34px / weight 750 / letter-spacing -1.53px / #101A2E
 *   설명     14px / line-height 23.1px / #5F6F86
 *
 * 117 저장소 선택 화면이 같은 값을 인라인으로 갖고 있는데, 이번에 화면이 9개
 * 늘어나면서 두 번째 이상의 소비자가 생겼으므로 여기로 모은다. 117 화면은 이미
 * develop에 병합돼 있어 이 티켓에서 건드리지 않고, 후속에서 이 컴포넌트로 옮긴다.
 *
 * `aside`는 Final의 우측 상단 보조 영역 자리다. 표시할 실제 데이터가 없는 화면은
 * 넘기지 않으면 되고 그 경우 레이아웃이 그대로 유지된다.
 *
 * 제목 크기 단계는 `index.css`의 `.gj-page-title`이 갖는다. 1024~1535px에서 Final과
 * 같은 34px이고 그 위에서만 36 → 38px로 조금 키운다. 설명은 키우지 않는다.
 */
export function PageHero({
  eyebrow,
  title,
  description,
  aside,
}: {
  eyebrow?: string
  title: string
  description?: string
  aside?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="gj-hero-text">
        {eyebrow !== undefined && eyebrow !== '' && (
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">{eyebrow}</p>
        )}
        <h1
          className={`gj-page-title leading-[1.16] font-[750] tracking-[-0.045em] text-brand-ink ${eyebrow ? 'mt-2' : ''}`}
        >
          {title}
        </h1>
        {description !== undefined && description !== '' && (
          <p className="mt-3 text-[14px] leading-[1.65] text-brand-muted">{description}</p>
        )}
      </div>
      {aside}
    </header>
  )
}
