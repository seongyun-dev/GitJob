/**
 * 건수 지표.
 *
 * **정수와 단위만 받는다.** 퍼센트 포맷터를 두지 않는다.
 * 매칭률 같은 비율은 행동을 유발하지 않는 수치라 와이어프레임 1-1이 금지했고,
 * 이 컴포넌트만 제공하면 퍼센트를 만들려는 시도가 리뷰에 걸린다.
 *
 * emphasis 기본값은 neutral이다. S4-B의 "하나만 액센트" 규칙 때문이다.
 */
export function CountStat({
  label,
  value,
  unit,
  emphasis = 'neutral',
  caption,
}: {
  label: string
  value: number
  unit: string
  emphasis?: 'accent' | 'neutral'
  caption?: string
}) {
  const valueTone = emphasis === 'accent' ? 'text-tone-accent' : 'text-neutral-900'

  return (
    <div>
      <p className="text-xs text-tone-neutral">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${valueTone}`}>
        {value.toLocaleString('ko-KR')}
        <span className="ml-1 text-sm font-normal text-tone-neutral">{unit}</span>
      </p>
      {caption !== undefined && <p className="mt-1 text-xs text-tone-neutral">{caption}</p>}
    </div>
  )
}
