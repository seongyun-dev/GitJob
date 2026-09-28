/**
 * 접어 둔 추천 이유 · 티켓 S15P21E102-377.
 *
 * <h2>왜 컴포넌트로 두는가</h2>
 *
 * 학습 추천(`/recommendations`)과 관련 공고(`/what-if`)가 같은 토글을 각자 적어 두고
 * 있었다. 그래서 한쪽만 고쳤을 때 같은 흐름 안에서 한 화면은 브랜드 표기, 다른 화면은
 * 브라우저 기본 검은 삼각형으로 갈렸다. 표기를 한 곳에 두면 다음에도 갈리지 않는다.
 *
 * <h2>기본 표현을 쓰지 않는 이유</h2>
 *
 * 기본 `summary` 는 검은 삼각형과 검은 outline 을 그린다. 이 서비스에는 그 두 색이
 * 어디에도 없어서 닫힌 상태만 남의 화면처럼 보였다. marker 를 끄고 같은 자리에 ▸ 를
 * 두되 펼치면 회전시킨다 — 내 기술 표가 쓰는 표기와 같은 모양이다.
 *
 * 초점 표시는 없애지 않는다. 지우면 키보드 사용자가 지금 어디에 있는지 알 수 없다.
 * `gj-focus-ring` 이 `gj-clickable` 과 같은 선언을 공유하므로 링 값은 복제되지 않는다.
 * `gj-clickable` 자체를 쓰지 않는 것은 그쪽이 hover 에 `translateY(-3px)` 이 붙는
 * 버튼·카드용이라, 본문 안 글자 토글에 붙이면 글자가 떠오르기 때문이다.
 */
export function ReasonsDisclosure({
  reasons,
  label = '추천 이유',
}: {
  reasons: readonly string[]
  /** 기본값이 아닌 문구가 필요한 자리를 위해 열어 둔다. 문구는 호출부가 정한다. */
  label?: string
}) {
  if (reasons.length === 0) {
    return null
  }

  return (
    <details className="group mt-5 text-[12px] text-brand-muted">
      <summary className="gj-focus-ring flex w-fit cursor-pointer list-none items-center gap-1.5 rounded-[6px] font-semibold select-none hover:text-brand-ink [&::-webkit-details-marker]:hidden">
        <span
          aria-hidden
          className="text-[10px] text-brand-faint transition-transform group-open:rotate-90"
        >
          ▸
        </span>
        {label}
      </summary>
      <ul className="mt-2 grid gap-1.5">
        {reasons.map((reason) => (
          <li
            key={reason}
            className="flex gap-2 text-[12.5px] leading-[1.6] text-brand-muted"
          >
            <span aria-hidden className="text-brand-600">
              ·
            </span>
            {reason}
          </li>
        ))}
      </ul>
    </details>
  )
}
