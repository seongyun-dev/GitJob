/**
 * 지표 스트립 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`가 `08 My Evidence`와 `17 Skill Gap`에서 같은 형태를 쓴다.
 * 카드 여러 장이 아니라 **한 장의 카드를 세로 분할선으로 나눈 띠**다(실측 `335.5 x 4`).
 * 값들이 같은 분석·같은 비교 집합에서 나온 것이라 하나의 면으로 묶인다.
 *
 * 지표 **이름과 기준**은 제품 정의라 데이터 없이도 보여줄 수 있다. **값은 호출부가
 * 정한다.** 값이 없으면 `note`로 무엇을 기다리는지 말한다. `0`이나 `-`로 채우지
 * 않는다. `0`은 "확인했더니 없었다"는 거짓이 되고 `-`는 아무것도 알려주지 않는다.
 */
export type StatItem = {
  label: string
  /** 값 자리 문구. 실제 값이 없으면 대기 상태를 적는다 */
  note: string
  caption: string
  /**
   * 있으면 그 칸이 버튼이 된다. 숫자를 센 대상 목록을 여는 자리다.
   *
   * 셀 대상이 없을 때(분석 전·0개)는 호출부가 아예 넘기지 않는다. 눌러도 빈 목록만
   * 나오는 버튼을 두면 화면이 "볼 게 있다"고 거짓말을 한다.
   */
  onOpen?: () => void
}

/**
 * 열 수는 항목 수를 따라간다. Tailwind가 클래스명을 정적으로 스캔하므로
 * 문자열을 조립하지 않고 미리 적어 둔다.
 */
const COLUMNS: Readonly<Record<number, string>> = {
  3: 'lg:grid-cols-3',
  4: 'lg:grid-cols-4',
}

export function StatStrip({ items }: { items: readonly StatItem[] }) {
  const columns = COLUMNS[items.length] ?? 'lg:grid-cols-4'

  return (
    <div
      className={`grid grid-cols-1 divide-y divide-brand-line overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)] sm:grid-cols-2 lg:divide-x lg:divide-y-0 ${columns}`}
    >
      {items.map((item) => (
        <StatCell key={item.label} item={item} />
      ))}
    </div>
  )
}

function StatCell({ item }: { item: StatItem }) {
  const body = (
    <>
      <p className="text-[13px] font-semibold text-brand-ink-soft">{item.label}</p>
      <p className="mt-2 text-[15px] font-[750] text-brand-faint">{item.note}</p>
      <p className="mt-1.5 text-[12.5px] leading-[1.5] text-brand-faint">{item.caption}</p>
    </>
  )

  if (item.onOpen === undefined) {
    return <div className="px-6 py-5">{body}</div>
  }

  return (
    <button
      type="button"
      onClick={item.onOpen}
      className="px-6 py-5 text-left hover:bg-tone-accent-bg/40"
    >
      {body}
      <span className="mt-1.5 inline-block text-[12px] font-bold text-tone-accent underline">
        목록 보기
      </span>
    </button>
  )
}
