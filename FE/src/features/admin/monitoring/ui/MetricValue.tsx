import type { UsageLevel } from '@/features/admin/monitoring/model/thresholds'

/**
 * 지표 값 표기 · 티켓 S15P21E102-210.
 *
 * 값이 없을 때 `0`을 그리지 않는 규칙이 여기 한곳에 있다. 값 없음은 `—`이고, 마우스를
 * 올리면 왜 비었는지 나온다. 이 화면에서 가장 위험한 버그는 예외가 아니라 조용한 0이다 —
 * CPU를 못 읽었는데 0%가 뜨면 운영자는 서버가 한가하다고 읽는다.
 */

const NO_VALUE = '—'

const LEVEL_TEXT: Readonly<Record<UsageLevel, string>> = {
  NORMAL: 'text-brand-ink',
  WARNING: 'text-tone-caution',
  CRITICAL: 'text-tone-danger',
}

const LEVEL_BAR: Readonly<Record<UsageLevel, string>> = {
  NORMAL: 'bg-brand-600',
  WARNING: 'bg-tone-caution',
  CRITICAL: 'bg-tone-danger',
}

/**
 * 큰 숫자 하나.
 *
 * `text`가 `null`이면 값을 얻지 못한 것이다. 그때는 임계치 색을 쓰지 않는다 — 회색이
 * "모른다"를 뜻하고, 파란색은 "정상 범위"를 뜻하기 때문이다.
 */
export function MetricValue({
  text,
  level = 'NORMAL',
  size = 'md',
  unit,
}: {
  text: string | null
  level?: UsageLevel
  size?: 'sm' | 'md' | 'lg'
  unit?: string
}) {
  const sizeClass =
    size === 'lg' ? 'text-[28px]' : size === 'md' ? 'text-[22px]' : 'text-[18px]'

  if (text === null) {
    return (
      <span
        className={`${sizeClass} font-extrabold tracking-[-0.04em] text-brand-faint tabular-nums`}
        title="값을 얻지 못했습니다"
      >
        {NO_VALUE}
      </span>
    )
  }

  return (
    <span className="inline-flex items-baseline gap-1">
      <span
        className={`${sizeClass} font-extrabold tracking-[-0.04em] tabular-nums ${LEVEL_TEXT[level]}`}
      >
        {text}
      </span>
      {unit !== undefined && (
        <span className="text-[12px] font-bold text-brand-faint">{unit}</span>
      )}
    </span>
  )
}

/**
 * 사용률 바.
 *
 * 값이 없으면 채우지 않고 빈 트랙만 남긴다. 0%로 채운 바는 "측정했더니 0"으로 읽힌다.
 */
export function UsageBar({
  percent,
  level = 'NORMAL',
  label,
}: {
  percent: number | null
  level?: UsageLevel
  label: string
}) {
  return (
    <div
      className="h-1 overflow-hidden rounded-sm bg-[#EEF1F6]"
      role="img"
      aria-label={percent === null ? `${label} 값 없음` : `${label} ${Math.round(percent)}%`}
    >
      {percent !== null && (
        <div
          className={`h-full rounded-sm ${LEVEL_BAR[level]}`}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      )}
    </div>
  )
}

/** 값이 없을 때 보조 설명 자리에 넣는 짧은 표기. */
export function MetricCaption({ text }: { text: string | null }) {
  return (
    <p className="mt-1.5 text-[11.5px] leading-[1.5] text-brand-faint">
      {text ?? '값 없음'}
    </p>
  )
}
