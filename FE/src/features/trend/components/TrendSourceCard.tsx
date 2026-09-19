import { Link } from 'react-router'
import type { TrendSourceView } from '@/features/trend/model/view'
import { MeterBar } from '@/shared/ui/MeterBar'
import type { StateKind } from '@/shared/ui/StateCard'
import { stateKindDisplayName } from '@/shared/presentation/userFacingLabels'

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
 * 그래서 막대의 분모가 **그 출처의 1위 값**이다. 세 출처의 막대 길이를 서로 비교할 수
 * 있게 만들면 규칙을 화면이 깬다. `unit`을 항상 크게 보여주는 것도 같은 이유다.
 *
 * 상태가 READY가 아니면 순위 자리에 `StateCard`를 둔다. 준비 중·미지원은 오류가
 * 아니므로 그 사실을 그대로 적고, 값을 지어내지 않는다.
 */

/** `DataStatus`를 상태 카드 종류로 옮긴다. 카드가 받는 값 목록이 닫혀 있어 매핑이 필요하다. */
const STATE_KIND: Readonly<Record<TrendSourceView['status'], StateKind>> = {
  READY: 'LOADING',
  PREPARING: 'PREPARING',
  PARTIAL: 'PARTIAL',
  NO_DATA: 'NO_DATA',
  INSUFFICIENT_DATA: 'INSUFFICIENT_DATA',
  NOT_SUPPORTED: 'NOT_SUPPORTED',
  FAILED: 'ERROR',
}

const RANK_COLUMNS = ['#', '기술', '비중', '전기 대비'] as const
const RANK_TEMPLATE = '22px minmax(0,1fr) 64px 62px'

/**
 * 기간 이동 · 티켓 S15P21E102-329.
 *
 * 없으면 카드는 이전과 똑같이 기간 하나만 적는다. 이동이 가능한 카드에만 버튼이 붙고,
 * 양 끝에서는 disabled 다 — 누를 수는 있는데 아무 일도 안 나는 버튼을 두지 않는다.
 */
export interface TrendPeriodNavigation {
  periods: readonly string[]
  selected: string
  onSelect: (period: string) => void
}

export function TrendSourceCard({
  source,
  navigation,
}: {
  source: TrendSourceView
  navigation?: TrendPeriodNavigation
}) {
  const index = navigation === undefined ? -1 : navigation.periods.indexOf(navigation.selected)
  const previous = index > 0 ? navigation?.periods[index - 1] : undefined
  const next =
    navigation !== undefined && index >= 0 && index < navigation.periods.length - 1
      ? navigation.periods[index + 1]
      : undefined

  const top = source.maximumObservedValue

  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
            {source.label}
          </p>
          <h2 className="mt-1.5 text-[16px] font-[750] tracking-[-0.02em] text-brand-ink">
            {source.unit}
          </h2>
        </div>
        {source.status !== 'READY' && (
          <span className="shrink-0 rounded-full border border-brand-line bg-white px-2.5 py-1 text-[10.5px] font-bold text-brand-faint">
            {stateKindDisplayName(STATE_KIND[source.status])}
          </span>
        )}
      </div>
      {navigation === undefined || navigation.periods.length <= 1 ? (
        <p className="mt-1.5 text-[12px] leading-[1.55] text-brand-faint">{source.basis}</p>
      ) : (
        <div className="mt-1.5 flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => previous !== undefined && navigation.onSelect(previous)}
            disabled={previous === undefined}
            aria-label="이전 기간"
            className="flex size-6 shrink-0 items-center justify-center rounded-[7px] border border-brand-line bg-white text-[12px] leading-none text-brand-faint transition-colors enabled:hover:text-brand-ink disabled:opacity-35"
          >
            ‹
          </button>
          <p
            aria-live="polite"
            className="min-w-0 flex-1 text-center text-[12px] leading-[1.55] font-[750] text-brand-ink-soft tabular-nums"
          >
            {source.basis}
          </p>
          <button
            type="button"
            onClick={() => next !== undefined && navigation.onSelect(next)}
            disabled={next === undefined}
            aria-label="다음 기간"
            className="flex size-6 shrink-0 items-center justify-center rounded-[7px] border border-brand-line bg-white text-[12px] leading-none text-brand-faint transition-colors enabled:hover:text-brand-ink disabled:opacity-35"
          >
            ›
          </button>
        </div>
      )}
      {navigation !== undefined && navigation.periods.length > 1 && (
        <p className="mt-1 text-center text-[10.5px] text-brand-faint tabular-nums">
          {`${index + 1} / ${navigation.periods.length} 기간`}
        </p>
      )}

      {source.rows.length === 0 ? (
        <div className="mt-4 rounded-[12px] border border-brand-line bg-[#F7F9FC] px-4 py-4">
          <p className="text-[12.5px] leading-[1.65] text-brand-muted">
            {source.scopeNote ?? source.footnote}
          </p>
        </div>
      ) : (
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
            <ul className="grid gap-2.5">
              {source.rows.map((row) => (
                <li key={row.techName}>
                  <div
                    className="grid items-center gap-2.5"
                    style={{ gridTemplateColumns: RANK_TEMPLATE }}
                  >
                    <span className="text-[11px] font-extrabold tabular-nums text-brand-faint">
                      {String(row.rank).padStart(2, '0')}
                    </span>
                    {/*
                      링크는 `techId`를 쓴다. 표시 이름으로 만들면
                      `Apache Kafka` → `apache-kafka`가 되는데 실제 id는 `kafka`라
                      상세 화면이 기술을 찾지 못한다.
                    */}
                    <Link
                      to={`/trends/${row.techId}`}
                      className="truncate text-[13px] font-[750] text-brand-ink hover:text-brand-600"
                    >
                      {row.techName}
                    </Link>
                    <span className="text-[13px] font-[750] tabular-nums text-brand-ink-soft">
                      {row.share}
                    </span>
                    <span
                      className={`text-right text-[13px] font-[750] tabular-nums ${
                        row.direction === 'UP' ? 'text-tone-success' : 'text-brand-faint'
                      }`}
                    >
                      {row.delta}
                    </span>
                  </div>
                  {/*
                    막대 분모는 이 출처의 1위 값이다. 출처 간 길이를 비교할 수 있게
                    만들면 "합치지 않는다"는 규칙을 화면이 깬다.
                  */}
                  {/*
                    막대 분모는 이 출처의 1위 값이다. 값이 없는 행(`—`)은 막대를
                    그리지 않는다 -- 0 길이 막대는 "관측했더니 0"으로 읽힌다.
                  */}
                  {top !== null && (
                    <div className="mt-1.5">
                      <MeterBar
                        value={row.observedValue}
                        total={top}
                        tone={row.rank === 1 ? 'accent' : 'muted'}
                        height={4}
                      />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {/*
        품질 확인 중인 값을 순위에서 빼지 않되, 충분한 근거처럼 보이게 하지도 않는다
        · 티켓 S15P21E102-327.

        행마다 배지를 달면 표가 상태 딱지로 뒤덮여 정작 순위를 읽기 어렵다. 그리고
        이 값들은 틀린 값이 아니라 아직 품질 확인이 끝나지 않은 실측이므로, 행을
        일일이 깎아내릴 이유도 없다. 카드 아래에 한 줄로 한 번만 적는다.
      */}
      {source.rows.some((row) => row.dataStatus !== 'READY') && (
        <p className="mt-3 text-[11.5px] leading-[1.55] text-brand-faint">
          일부 데이터는 품질 확인이 진행 중입니다.
        </p>
      )}
      {source.unobservedRows.length > 0 && (
        <p className="mt-3 text-[11.5px] leading-[1.55] text-brand-faint">
          순위 미포함: {source.unobservedRows.map((row) => `${row.techName} (${stateKindDisplayName(STATE_KIND[row.dataStatus])})`).join(', ')}
        </p>
      )}
    </section>
  )
}
