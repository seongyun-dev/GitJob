/**
 * 시계열 선 그래프 · 티켓 S15P21E102-210.
 *
 * 차트 라이브러리를 넣지 않았다. 이 화면이 그리는 것은 축 없는 선 두세 개뿐이고
 * (확정 디자인의 CPU·Memory 겹친 선, Network IN/OUT), 그 정도에 의존성을 하나 더
 * 들이면 번들만 커진다. 확정 디자인 자체도 raw SVG로 그린다.
 *
 * 부드러운 곡선은 디자인의 `path()`와 같은 방식이다 — 점 사이를 수평 제어점 두 개의
 * 3차 베지에로 잇는다. 꺾인 직선보다 값의 추세가 읽힌다.
 *
 * `viewBox`에 `preserveAspectRatio="none"`을 쓰므로 폭은 부모가 정한다. 화면 폭에 따라
 * 그래프만 늘어나고 선 두께는 유지된다.
 */

export interface ChartSeries {
  id: string
  label: string
  /** 선 색. 토큰 값을 호출부가 넘긴다. */
  color: string
  /** 면 색. 없으면 선만 그린다. */
  fill?: string
  width?: number
  values: readonly number[]
}

const PADDING = 4

interface Geometry {
  path: string
  areaPath: string
  lastX: number
  lastY: number
}

function geometry(
  values: readonly number[],
  width: number,
  height: number,
  max: number,
): Geometry | null {
  if (values.length === 0) {
    return null
  }

  const usableWidth = width - PADDING * 2
  const baseline = height - PADDING
  const x = (index: number) =>
    values.length === 1
      ? PADDING + usableWidth / 2
      : PADDING + (index * usableWidth) / (values.length - 1)
  // max가 0이면 모든 점이 바닥에 붙는다. 0으로 나누지 않기 위한 방어이기도 하다.
  const y = (value: number) =>
    baseline - (max <= 0 ? 0 : (Math.min(value, max) / max) * (height - PADDING * 2 - 2))

  // 색인 접근을 명시적으로 좁힌다(`noUncheckedIndexedAccess`). 빠진 점을 0으로
  // 채우지 않고 그 구간을 건너뛴다 — 0은 "측정했더니 0"이라는 다른 뜻이다.
  const first = values[0]
  if (first === undefined) {
    return null
  }

  let path = `M${x(0)},${y(first)}`
  let lastIndex = 0
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1]
    const current = values[index]
    if (previous === undefined || current === undefined) {
      continue
    }
    const previousX = x(index - 1)
    const currentX = x(index)
    const control = (currentX - previousX) / 2
    path +=
      ` C${previousX + control},${y(previous)}` +
      ` ${currentX - control},${y(current)}` +
      ` ${currentX},${y(current)}`
    lastIndex = index
  }

  const last = values[lastIndex] ?? first
  return {
    path,
    areaPath: `${path} L${x(lastIndex)},${baseline} L${x(0)},${baseline} Z`,
    lastX: x(lastIndex),
    lastY: y(last),
  }
}

export function LineChart({
  series,
  max,
  height = 150,
  width = 720,
  ariaLabel,
}: {
  series: readonly ChartSeries[]
  /** y축 상한. 백분율은 100, 처리량은 호출부가 데이터에서 정한다. */
  max: number
  height?: number
  width?: number
  ariaLabel: string
}) {
  const drawn = series
    .map((item) => ({ item, shape: geometry(item.values, width, height, max) }))
    .filter((entry): entry is { item: ChartSeries; shape: Geometry } => entry.shape !== null)

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel}
      className="block overflow-visible"
    >
      {/* 눈금선. 값이 없어도 그린다 — 그래프가 들어갈 자리라는 것은 데이터와 무관하다. */}
      {[0.25, 0.5, 0.75].map((fraction) => {
        const y = height - PADDING - fraction * (height - PADDING * 2 - 2)
        return (
          <line key={fraction} x1={0} x2={width} y1={y} y2={y} stroke="#EEF1F6" strokeWidth={1} />
        )
      })}

      {drawn.map(({ item, shape }) => (
        <g key={item.id}>
          {item.fill !== undefined && <path d={shape.areaPath} fill={item.fill} />}
          <path
            d={shape.path}
            fill="none"
            stroke={item.color}
            strokeWidth={item.width ?? 2}
            strokeLinecap="round"
          />
          {/* 마지막 점을 찍어 현재 값이 어디인지 보이게 한다. */}
          <circle
            cx={shape.lastX}
            cy={shape.lastY}
            r={3.5}
            fill="#fff"
            stroke={item.color}
            strokeWidth={2}
          />
        </g>
      ))}
    </svg>
  )
}

/** 그래프 아래 시각 축. 점이 없으면 아무것도 그리지 않는다. */
export function TimeAxis({ labels }: { labels: readonly string[] }) {
  if (labels.length === 0) {
    return null
  }
  return (
    <div className="mt-1.5 flex justify-between text-[11px] text-brand-faint tabular-nums">
      {labels.map((label, index) => (
        <span key={`${label}-${index}`}>{label}</span>
      ))}
    </div>
  )
}
