import { Link } from 'react-router'

/**
 * 공고 필터 레일 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `02 Job Match`는 본문 왼쪽에 260px 필터 레일을 둔다
 * (실측 `260px 1082px`). 지역 · 경력 두 축과 적용 버튼, 그리고 현재 직무 표시다.
 *
 * **컨트롤을 전부 비활성으로 둔다.** 필터를 적용하려면 공고 조회 API가 있어야 하는데
 * develop에 없다. 누를 수 있는데 아무 일도 없는 셀렉트와 버튼을 만들지 않는다.
 * 축과 선택지 이름은 제품 정의라 그대로 보여주고, 동작만 막는다.
 *
 * 선택지 값(서울·경기 등)은 v2가 예시로 적은 것이라 옮기지 않는다. 지역·경력 목록은
 * 수집된 공고에서 나오는 값이고 조회 API가 준다.
 */
const AXES = [
  { label: '지역', hint: '수집된 공고의 지역이 목록으로 들어옵니다' },
  { label: '경력', hint: '공고가 요구하는 경력 구간이 들어옵니다' },
] as const

export function JobFilterRail() {
  return (
    <aside className="rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">FILTER</p>

      <div className="mt-4 grid gap-4">
        {AXES.map((axis) => (
          <div key={axis.label}>
            <label className="text-[12.5px] font-semibold text-brand-ink-soft">{axis.label}</label>
            <select
              disabled
              aria-label={`${axis.label} 필터`}
              title="공고 조회 API가 준비되면 사용할 수 있습니다."
              className="mt-1.5 w-full rounded-[10px] border border-brand-line bg-[#F7F9FC] px-3 py-2.5 text-[13px] text-brand-faint disabled:cursor-not-allowed"
            >
              <option>전체</option>
            </select>
            <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-faint">{axis.hint}</p>
          </div>
        ))}
      </div>

      <button
        type="button"
        disabled
        title="공고 조회 API가 준비되면 사용할 수 있습니다."
        className="mt-5 w-full rounded-[10px] border border-brand-line bg-[#F7F9FC] px-4 py-2.5 text-[13px] font-[750] text-brand-faint disabled:cursor-not-allowed"
      >
        필터 적용
      </button>

      <div className="mt-5 border-t border-brand-line pt-4">
        <p className="text-[12.5px] text-brand-faint">직무</p>
        <p className="mt-1 text-[13.5px] font-[750] text-brand-ink">선택 전</p>
        <Link
          to="/roles"
          className="mt-1.5 inline-block text-[12.5px] font-semibold text-brand-600 hover:underline"
        >
          직무 선택하기
        </Link>
      </div>
    </aside>
  )
}
