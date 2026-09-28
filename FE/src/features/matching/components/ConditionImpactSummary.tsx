/**
 * 추천 기술이 필수 또는 우대로 언급된 활성 공고 수.
 */
export function formatImpactIncrease(count: number): string {
  return `+${count.toLocaleString('ko-KR')}건`
}

export function ConditionImpactSummary({
  requiredCount,
  preferredCount,
  emphasis = false,
}: {
  requiredCount: number
  preferredCount: number
  emphasis?: boolean
}) {
  return (
    <div>
      <p className="text-[11.5px] font-semibold text-brand-faint">필수 공고</p>
      <p
        className={`mt-1 font-[850] leading-none tracking-[-0.05em] ${
          emphasis ? 'text-[54px] text-brand-600' : 'text-[42px] text-brand-ink-soft'
        }`}
      >
        {requiredCount.toLocaleString('ko-KR')}건
      </p>
      <p className="mt-2 text-[11.5px] leading-[1.5] text-brand-faint">
        우대 공고 {preferredCount.toLocaleString('ko-KR')}건
      </p>
    </div>
  )
}
