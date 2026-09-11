/**
 * 비율 막대 · 티켓 S15P21E102-213.
 *
 * 확정 디자인 `Final v2`가 같은 막대를 여섯 화면에서 쓴다(02 충족 분포 · 16 직무별
 * 요구 기술 · 17 Gap 순위 · 10 매칭 변화 · 12 출처별 비중 · 13 월별 추이).
 * 화면마다 인라인으로 적으면 높이와 라운드가 조금씩 어긋난다.
 *
 * **분모를 반드시 받는다.** `percent`를 직접 받으면 호출부가 비율을 계산해 넘기게
 * 되는데, 이 제품에서 비율을 만드는 것은 화면의 일이 아니다. `value`와 `total`을
 * 받아 여기서 폭만 환산하면 화면 코드에 계산식이 남지 않는다.
 *
 * `total`이 0이면 폭 0으로 그린다. 0으로 나누는 대신 "아무것도 차지하지 않음"이
 * 맞고, 그 상태를 숨기면 빈 결과가 화면에서 사라진다.
 */
export function MeterBar({
  value,
  total,
  tone = 'accent',
  height = 8,
}: {
  value: number
  total: number
  /** accent: 강조 · muted: 보조 · warn: 부족 구간 */
  tone?: 'accent' | 'muted' | 'warn'
  height?: number
}) {
  const percent = total <= 0 ? 0 : Math.min(100, Math.round((value / total) * 100))
  const fill =
    tone === 'accent'
      ? 'bg-[linear-gradient(90deg,#2F5EEB,#7EAAFF)]'
      : tone === 'warn'
        ? 'bg-[#F0C27B]'
        : 'bg-[#AFC8FF]'

  return (
    <span
      className="block overflow-hidden rounded-full bg-[#EDF1F7]"
      style={{ height }}
      aria-hidden
    >
      <span className={`block h-full rounded-full ${fill}`} style={{ width: `${percent}%` }} />
    </span>
  )
}

/**
 * 필수 기술 충족을 칸으로 보여주는 막대.
 *
 * v2의 `02 Job Match` 공고 카드가 요구 기술 수만큼 칸을 나눠 각 칸을 충족 상태로
 * 칠한다. 비율 하나로 합치지 않는 이유는 "4개 중 3개"와 "8개 중 6개"가 같은 75%라도
 * 다른 상황이기 때문이다.
 */
export function SegmentBar({ marks }: { marks: readonly ('HAVE' | 'WEAK' | 'NONE')[] }) {
  const color: Readonly<Record<'HAVE' | 'WEAK' | 'NONE', string>> = {
    HAVE: 'bg-brand-600',
    WEAK: 'bg-[#F0C27B]',
    NONE: 'bg-[#E4E9F1]',
  }

  return (
    <span className="flex gap-1" aria-hidden>
      {marks.map((mark, index) => (
        <i key={index} className={`h-2 flex-1 rounded-[2px] ${color[mark]}`} />
      ))}
    </span>
  )
}
