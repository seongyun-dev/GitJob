import type { TrendSeriesFixture } from '@/mocks/types'
import { StateCard } from '@/shared/ui/StateCard'
import type { StateKind } from '@/shared/ui/StateCard'

/**
 * 기간별 추이 막대 · 화면 13 Trend Detail.
 *
 * 확정 디자인 `Final v2`는 최근 12개월을 세로 막대로 그리고 마지막 달만 진하게
 * 칠한다. 선 그래프가 아닌 이유는 이 지표가 연속량이 아니라 **기간별 관측값**이고,
 * 누락 기간을 보간하지 않기 때문이다(`docs/ai/c-public-trend.md`). 선으로 이으면
 * 없는 달을 화면이 만들어낸다.
 *
 * **높이 분모는 그 계열의 최대값이다.** 출처마다 단위가 달라(`공고 건수` ·
 * `질문 비중`) 여러 계열을 한 축에 겹쳐 그리지 않는다. 한 계열 안에서의 상대
 * 크기만 보여준다.
 *
 * 라이브러리를 쓰지 않는다. 이 화면이 필요한 것은 막대 12개이고, 축 라벨과 눈금이
 * 없는 형태라 차트 라이브러리를 넣으면 번들만 커진다. 관리자 모니터링의
 * `ui/LineChart.tsx`도 같은 이유로 직접 그린다.
 */
const SERIES_STATE: Readonly<Record<TrendSeriesFixture['status'], StateKind>> = {
  READY: 'LOADING',
  PREPARING: 'PREPARING',
  PARTIAL: 'PARTIAL',
  NO_DATA: 'NO_DATA',
  INSUFFICIENT_DATA: 'INSUFFICIENT_DATA',
  NOT_SUPPORTED: 'NOT_SUPPORTED',
  FAILED: 'ERROR',
}

const STATE_TITLE: Readonly<Record<TrendSeriesFixture['status'], string>> = {
  READY: '불러오는 중',
  PREPARING: '데이터를 준비하고 있어요',
  PARTIAL: '일부 기간만 집계됐어요',
  NO_DATA: '이 출처에는 데이터가 없어요',
  INSUFFICIENT_DATA: '비교할 기간이 부족해요',
  NOT_SUPPORTED: '이 출처는 이 기술을 지원하지 않아요',
  FAILED: '추이를 불러오지 못했어요',
}

export function TrendBarChart({ series }: { series: TrendSeriesFixture }) {
  if (series.points.length === 0) {
    return (
      <StateCard
        kind={SERIES_STATE[series.status]}
        title={STATE_TITLE[series.status]}
        description={series.note}
      />
    )
  }

  const max = Math.max(...series.points.map((point) => point.value))
  const lastIndex = series.points.length - 1

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-3">
        <p className="text-[28px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
          {series.latestText}
        </p>
        {series.deltaText !== null && (
          <p className="text-[13px] font-[750] text-tone-success">{series.deltaText}</p>
        )}
        <p className="text-[11.5px] text-brand-faint">{series.axisLabel}</p>
      </div>

      {/*
        막대 높이를 `%`로 주고 컨테이너에 고정 높이를 준다. `aspect-ratio`로 두면
        좁은 화면에서 막대가 눌려 값 차이가 안 보인다.
      */}
      <div className="mt-4 flex h-[136px] items-end gap-1.5" aria-hidden>
        {series.points.map((point, index) => (
          <span
            key={point.period}
            className={`flex-1 rounded-t-[5px] ${
              index === lastIndex
                ? 'bg-[linear-gradient(180deg,#3F73FF,#2F5EEB)]'
                : 'bg-[#AFC8FF]'
            }`}
            style={{ height: `${Math.round((point.value / max) * 100)}%` }}
          />
        ))}
      </div>
      <div className="mt-2 flex gap-1.5">
        {series.points.map((point, index) => (
          <span
            key={point.period}
            className={`flex-1 truncate text-center text-[10px] ${
              index === lastIndex ? 'font-extrabold text-brand-ink-soft' : 'text-brand-faint'
            }`}
          >
            {point.period}
          </span>
        ))}
      </div>

      {/*
        낭독용 표. 막대는 `aria-hidden`이라 값이 읽히지 않으므로 같은 값을 목록으로
        한 번 더 둔다. 화면에는 보이지 않는다.
      */}
      <ul className="sr-only">
        {series.points.map((point) => (
          <li key={point.period}>
            {point.period} {point.value}
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[11.5px] leading-[1.6] text-brand-faint">{series.note}</p>
    </div>
  )
}
