import { StateCard } from '@/shared/ui/StateCard'
import type { StateKind } from '@/shared/ui/StateCard'

/**
 * 출처별 트렌드 카드 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `12 Trend Overview`는 출처 셋을 나란히 놓는다
 * (실측 `437.3 x 3`, gap 16). 카드마다 출처 이름 · 상태 배지 · 지표 이름 · 측정 기준 ·
 * 순위 목록이 들어간다.
 *
 * **출처를 나란히 놓되 합치지 않는 것이 이 화면의 요점이다.** 채용공고 · GitHub ·
 * Stack Overflow는 측정 단위와 기간이 달라 순위를 출처 안에서만 비교한다. 종합 점수를
 * 만들지 않는다(PROJECT_GUIDE §1).
 *
 * 순위와 비중은 집계 API가 준다. 여기서는 출처와 측정 기준까지만 세운다.
 * v2의 `19.7%`, `↑ 7.1%` 같은 값은 demo라 옮기지 않는다.
 */
const RANK_COLUMNS = ['#', '기술', '비중', '전기 대비'] as const
const RANK_TEMPLATE = '22px minmax(0,1fr) 64px 62px'

export function TrendSourceCard({
  source,
  metric,
  basis,
  state,
  stateTitle,
  stateDescription,
}: {
  /** 출처 이름 */
  source: string
  /** 이 출처에서 무엇을 세는지 */
  metric: string
  /** 측정 범위와 기간 */
  basis: string
  state: StateKind
  stateTitle: string
  stateDescription: string
}) {
  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">{source}</p>
          <h2 className="mt-1.5 text-[16px] font-[750] tracking-[-0.02em] text-brand-ink">
            {metric}
          </h2>
        </div>
      </div>
      <p className="mt-1.5 text-[12px] leading-[1.55] text-brand-faint">{basis}</p>

      <div className="mt-4 overflow-hidden rounded-[12px] border border-brand-line">
        <div
          className="grid gap-2.5 bg-[#F7F9FC] px-3 py-2 text-[10px] font-extrabold tracking-[0.1em] text-brand-faint"
          style={{ gridTemplateColumns: RANK_TEMPLATE }}
        >
          {RANK_COLUMNS.map((label) => (
            <span key={label} className="truncate">
              {label}
            </span>
          ))}
        </div>
        <div className="p-3">
          <StateCard kind={state} title={stateTitle} description={stateDescription} />
        </div>
      </div>
    </section>
  )
}
