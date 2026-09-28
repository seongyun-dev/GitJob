import type { ReactNode } from 'react'

/**
 * 관리자 화면의 표 카드 · 티켓 S15P21E102-210.
 *
 * 확정 디자인 `Admin Monitoring v2`의 Server Detail 표다 — 흰 카드(radius 18 · 그림자) 안에
 * 헤더 행(11px / 800 / letter-spacing .08em · padding 12px 24px · border-bottom #E8EDF4) ·
 * 본문 행 · 각주(border-top · 12px)가 한 덩어리로 들어간다.
 *
 * 공용 `TableScaffold`를 쓰지 않는 이유: 그것은 `#evidence` 표를 옮긴 것으로 radius 14 ·
 * 회색 헤더 · **카드 배경 없음** · body padding 12px 이라 이 디자인과 다르다. 그대로 두면
 * 행이 페이지 그라데이션 위에 떠서 옆의 흰 카드들과 어긋나고(2026-09-11 화면 확인), 그 위에
 * 카드를 한 겹 씌우면 테두리가 두 겹이 된다. 그래서 관리자 표만 여기서 그린다.
 *
 * 골격을 남긴다는 원칙은 같다 — 컬럼 이름은 제품 정의이지 데이터가 아니라서 값이 없어도
 * 헤더는 그린다. `children`에 행 대신 상태 카드를 넘기면 그대로 그 자리에 들어간다.
 *
 * 좁은 화면에서는 헤더를 감춘다. 행은 호출부가 `.gj-mon-row`처럼 접히는 격자를 쓴다.
 */
export function AdminTable({
  columns,
  template,
  children,
  footer,
}: {
  /** 컬럼 이름. 제품 정의이지 데이터가 아니다 */
  columns: readonly string[]
  /** grid-template-columns. 행 격자와 같은 값이어야 열이 맞는다 */
  template: string
  /** 행들. 각 행이 자기 padding·border-top 을 갖는다 */
  children: ReactNode
  /** 카드 안 각주. 임계치 설명처럼 표 전체에 붙는 한 줄 */
  footer?: ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <div
        className="hidden gap-4 border-b border-[#E8EDF4] px-6 py-3 lg:grid"
        style={{ gridTemplateColumns: template }}
      >
        {columns.map((label) => (
          <span
            key={label}
            className="truncate text-[11px] font-extrabold tracking-[0.08em] text-brand-faint"
          >
            {label}
          </span>
        ))}
      </div>

      <div>{children}</div>

      {footer !== undefined && (
        <div className="border-t border-[#E8EDF4] px-6 py-3 text-[12px] leading-[1.5] text-brand-faint">
          {footer}
        </div>
      )}
    </div>
  )
}
