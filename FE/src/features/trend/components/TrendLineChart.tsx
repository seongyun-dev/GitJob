import { plotSeries, segments, VIEW_HEIGHT, VIEW_WIDTH } from '@/features/trend/model/lineGeometry'
import type { TrendSeriesView } from '@/features/trend/model/view'
import { StateCard } from '@/shared/ui/StateCard'
import type { StateKind } from '@/shared/ui/StateCard'

/**
 * 기간별 추이 선 그래프 · 화면 13 Trend Detail, 티켓 S15P21E102-329.
 *
 * <h2>막대에서 선으로 바꾼 이유와, 바꿀 때 지켜야 했던 것</h2>
 *
 * 앞선 `TrendBarChart`는 선 그래프를 의도적으로 피했고 그 근거를 주석에 적어 두었다 —
 * 이 지표는 연속량이 아니라 기간별 관측값이고, 점을 이으면 없는 기간을 화면이 만들어
 * 낸다. 그 지적은 옳다. 그래서 여기서는 **결손 기간에서 선을 끊는다.** 값이 있는 점만
 * 연속 구간으로 묶어 각각 따로 그리므로, 빠진 기간을 가로지르는 선분은 생기지 않는다.
 * 보간을 안 하는 선 그래프는 "이 두 점 사이는 우리도 모른다"를 그대로 보여준다.
 *
 * 추세를 읽기 쉬운 것이 선의 이점이고, 그것을 결손을 지어내는 대가로 얻지는 않는다.
 *
 * <h2>라이브러리를 넣지 않는다</h2>
 *
 * 이 화면이 필요한 것은 점 몇 개와 선 하나다. 관리자 모니터링의 `ui/LineChart.tsx`도
 * 같은 이유로 raw SVG다. 그쪽을 그대로 쓰지 않은 이유는 그 컴포넌트가
 * `values: readonly number[]`만 받아 **결손을 표현할 방법이 없기** 때문이다. 0으로
 * 채우면 이 화면에서 가장 중요한 구분이 사라진다.
 *
 * <h2>좌표계</h2>
 *
 * `viewBox`에 `preserveAspectRatio="none"`을 주고 폭은 부모가 정한다. 화면 폭에 따라
 * 그래프만 늘어나고 선 두께는 `vector-effect`로 유지된다. 좌표 계산 자체는
 * `model/lineGeometry`에 있다 — 그쪽은 타입만 import하므로 `node --test`가 읽을 수
 * 있고, **관측된 0과 미집계를 구별하는 규칙**이 테스트로 고정돼 있다.
 */

const SERIES_STATE: Readonly<Record<TrendSeriesView['status'], StateKind>> = {
  READY: 'LOADING',
  PREPARING: 'PREPARING',
  PARTIAL: 'PARTIAL',
  NO_DATA: 'NO_DATA',
  INSUFFICIENT_DATA: 'INSUFFICIENT_DATA',
  NOT_SUPPORTED: 'NOT_SUPPORTED',
  FAILED: 'ERROR',
}

const STATE_TITLE: Readonly<Record<TrendSeriesView['status'], string>> = {
  READY: '불러오는 중',
  PREPARING: '데이터를 준비하고 있어요',
  PARTIAL: '일부 기간만 집계됐어요',
  NO_DATA: '이 출처에는 데이터가 없어요',
  INSUFFICIENT_DATA: '비교할 기간이 부족해요',
  NOT_SUPPORTED: '이 출처는 이 기술을 지원하지 않아요',
  FAILED: '추이를 불러오지 못했어요',
}

/** 축 라벨을 몇 개까지 그릴지. 좁은 화면에서 글자가 겹치지 않는 상한이다. */
const MAX_LABELS = 6

/** 라벨이 겹치지 않을 만큼만 남긴다. 최신 기간은 항상 남긴다. */
function labelStride(count: number): number {
  return count <= MAX_LABELS ? 1 : Math.ceil(count / MAX_LABELS)
}

function countText(value: number | null): string {
  return value === null ? '미집계' : value.toLocaleString('ko-KR')
}

export function TrendLineChart({ series }: { series: TrendSeriesView }) {
  if (series.points.length === 0) {
    return (
      <StateCard
        kind={SERIES_STATE[series.status]}
        title={STATE_TITLE[series.status]}
        description={series.note}
      />
    )
  }

  const { plotted, max } = plotSeries(series.points)
  const runs = segments(plotted)
  const stride = labelStride(plotted.length)
  const missingCount = plotted.filter((point) => point.y === null).length
  /*
   * 관측이 하나라도 있고 그 최댓값이 0인 경우만이 "모두 0"이다. 전부 미집계일 때도
   * `max`는 0이지만 그것은 관측이 0이었다는 뜻이 아니다.
   */
  const allObservedZero = max === 0 && missingCount < plotted.length

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-3">
        <p className="text-[28px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
          {series.latestText ?? '—'}
        </p>
        {series.deltaText !== null && (
          <p className="text-[13px] font-[750] text-tone-success">{series.deltaText}</p>
        )}
        <p className="text-[11.5px] text-brand-faint">{series.axisLabel}</p>
      </div>

      {/*
        선은 SVG, 점은 HTML이다.

        `preserveAspectRatio="none"`으로 폭을 부모에 맡기면 x가 늘어나면서 `<circle>`이
        타원이 된다 — 카드 폭에서는 1.3배, 넓은 상세 화면에서는 2.6배까지 찌그러졌다.
        선은 늘어나도 의미가 그대로지만 점은 아니므로, 점과 결손 표시는 퍼센트 위치의
        HTML 레이어로 올려 동그라미를 유지한다. 축 계산은 한 곳(`plot`)에 그대로 둔다.
      */}
      <div className="relative mt-4 h-[136px] w-full">
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
          aria-hidden
        >
          {runs.map((run) => (
            <polyline
              key={`line-${run[0]?.period ?? 'empty'}`}
              points={run.map((point) => `${point.x},${point.y as number}`).join(' ')}
              fill="none"
              stroke="#3F73FF"
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>

        {plotted.map((point) => {
          const leftPercent = (point.x / VIEW_WIDTH) * 100
          if (point.y === null) {
            /*
              미집계 기간. 세로 점선만 남긴다 -- 점을 찍으면 값이 있는 것으로, 바닥에
              찍으면 0으로 읽힌다.
            */
            return (
              <span
                key={`gap-${point.period}`}
                title={`${point.period} · 미집계`}
                className="absolute top-0 bottom-0 w-0 border-l border-dashed border-[#D7DFEC]"
                style={{ left: `${leftPercent}%` }}
              />
            )
          }
          const topPercent = (point.y / VIEW_HEIGHT) * 100
          return (
            <span
              key={`dot-${point.period}`}
              title={`${point.period} · ${countText(point.value)}`}
              tabIndex={0}
              aria-label={`${point.period} ${countText(point.value)}`}
              className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full outline-none ring-offset-1 focus-visible:ring-2 focus-visible:ring-brand-600 ${
                point.isLatest
                  ? 'size-[11px] border-2 border-white bg-[#2F5EEB] shadow-[0_1px_4px_rgba(25,47,81,0.35)]'
                  : 'size-[8px] border-[1.5px] border-[#3F73FF] bg-white'
              }`}
              style={{ left: `${leftPercent}%`, top: `${topPercent}%` }}
            />
          )
        })}
      </div>

      {/*
        축 라벨. 점이 많으면 건너뛰어 그리되 최신 기간은 항상 남긴다 -- 마지막 값이
        어느 기간인지가 이 화면에서 가장 자주 확인하는 것이다.
      */}
      <div className="mt-2 flex">
        {plotted.map((point, index) => {
          const shown = point.isLatest || index % stride === 0
          return (
            <span
              key={`label-${point.period}`}
              className={`min-w-0 flex-1 truncate text-center text-[10px] ${
                point.isLatest ? 'font-extrabold text-brand-ink-soft' : 'text-brand-faint'
              }`}
            >
              {shown ? point.period : ' '}
            </span>
          )
        })}
      </div>

      {/*
        값 목록. 그래프의 `<title>`은 마우스에만 열리므로 키보드·낭독 사용자를 위해
        같은 값을 한 번 더 둔다. 결손 기간도 `미집계`로 함께 적는다.
      */}
      <details className="mt-3">
        <summary className="cursor-pointer text-[11.5px] font-semibold text-brand-muted hover:text-brand-ink">
          기간별 값 보기
        </summary>
        <ul className="mt-2 grid gap-1 sm:grid-cols-2">
          {plotted.map((point) => (
            <li
              key={`row-${point.period}`}
              className="flex items-baseline justify-between gap-2 text-[11.5px]"
            >
              <span className={point.isLatest ? 'font-bold text-brand-ink' : 'text-brand-faint'}>
                {point.period}
              </span>
              <span
                className={`tabular-nums ${
                  point.value === null ? 'text-brand-faint' : 'font-[750] text-brand-ink-soft'
                }`}
              >
                {countText(point.value)}
              </span>
            </li>
          ))}
        </ul>
      </details>

      {missingCount > 0 && (
        <p className="mt-2 text-[11.5px] leading-[1.6] text-brand-faint">
          {`집계되지 않은 기간 ${missingCount}개는 선을 잇지 않고 비워 두었습니다.`}
        </p>
      )}

      <p className="mt-2 text-[11.5px] leading-[1.6] text-brand-faint">{series.note}</p>

      {allObservedZero && (
        <p className="mt-1 text-[11.5px] leading-[1.6] text-brand-faint">
          관측값이 모두 0이라 선의 높이로는 차이를 보여줄 수 없습니다.
        </p>
      )}
    </div>
  )
}
