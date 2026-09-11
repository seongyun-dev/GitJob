import { Link } from 'react-router'
import type { TrendSourceFixture } from '@/mocks/types'
import { MeterBar } from '@/shared/ui/MeterBar'
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
 * 그래서 막대의 분모가 **그 출처의 1위 값**이다. 세 출처의 막대 길이를 서로 비교할 수
 * 있게 만들면 규칙을 화면이 깬다. `unit`을 항상 크게 보여주는 것도 같은 이유다.
 *
 * 상태가 READY가 아니면 순위 자리에 `StateCard`를 둔다. 준비 중·미지원은 오류가
 * 아니므로 그 사실을 그대로 적고, 값을 지어내지 않는다.
 */

/** `DataStatus`를 상태 카드 종류로 옮긴다. 카드가 받는 값 목록이 닫혀 있어 매핑이 필요하다. */
const STATE_KIND: Readonly<Record<TrendSourceFixture['status'], StateKind>> = {
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

export function TrendSourceCard({ source }: { source: TrendSourceFixture }) {
  const top = source.rows[0]?.share

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
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] ${
            source.status === 'READY'
              ? 'bg-tone-success-bg text-tone-success'
              : 'border border-brand-line bg-white text-brand-faint'
          }`}
        >
          {source.status}
        </span>
      </div>
      <p className="mt-1.5 text-[12px] leading-[1.55] text-brand-faint">{source.basis}</p>

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
          {source.rows.length === 0 ? (
            <StateCard
              kind={STATE_KIND[source.status]}
              title={
                source.status === 'NOT_SUPPORTED'
                  ? '이 출처는 지원하지 않아요'
                  : '데이터를 준비하고 있어요'
              }
              description={source.scopeNote ?? source.footnote}
            />
          ) : (
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
                  <div className="mt-1.5">
                    <MeterBar
                      value={Number.parseFloat(row.share)}
                      total={Number.parseFloat(top ?? row.share)}
                      tone={row.rank === 1 ? 'accent' : 'muted'}
                      height={4}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <p className="mt-3 text-[11.5px] leading-[1.6] text-brand-faint">{source.footnote}</p>
    </section>
  )
}
