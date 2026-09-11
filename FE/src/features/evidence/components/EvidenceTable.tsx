import type { ReactNode } from 'react'

/**
 * 기술별 판정 표 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `08 My Evidence` 표를 옮겼다.
 *   컬럼    기술 / PERSONAL / REPOSITORY / 대표 EVIDENCE / (상세 이동)
 *   열 폭   206.6 · 150 · 110 · 319.4 · 44  (gap 18)
 *
 * v2는 표 안에서 Level 구간별로 **그룹 헤더**를 둔다(`L2 이상 · 6개` 같은 줄).
 * 그 구간 이름은 등급 정책이 정하는 문구라 지금 굳히지 않는다. 대신 그룹을 넣을
 * 자리(`groups`)만 열어 두고, 정책이 확정되면 호출부에서 채운다.
 *
 * 행은 만들지 않는다. 기술명·Level·파일 경로는 전부 조회 API가 주는 값이다.
 */
const COLUMNS = ['기술', 'PERSONAL', 'REPOSITORY', '대표 EVIDENCE', ''] as const
/** 본문 행(`EvidenceRows`)이 같은 값을 써야 헤더와 밀리지 않으므로 내보낸다. */
export const EVIDENCE_TABLE_TEMPLATE = 'minmax(0,206fr) 150px 110px minmax(0,319fr) 44px'

export function EvidenceTable({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      {/*
        컬럼 헤더는 좁은 화면에서 감춘다. 다섯 열을 375px에 밀어 넣으면 글자가 겹친다.
        데이터가 붙으면 그 구간은 카드형 배치가 따로 필요하다.
      */}
      <div
        className="hidden gap-[18px] border-b border-brand-line px-[22px] py-3 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
        style={{ gridTemplateColumns: EVIDENCE_TABLE_TEMPLATE }}
      >
        {COLUMNS.map((label, index) => (
          <span key={label === '' ? `col-${index}` : label} className="truncate">
            {label}
          </span>
        ))}
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}
