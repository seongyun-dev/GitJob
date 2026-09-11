import { Link } from 'react-router'
import { JOB_FILTER_OPTIONS } from '@/mocks/fixtures/jobMatch'

/**
 * 공고 필터 레일 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `02 Job Match`는 본문 왼쪽에 260px 필터 레일을 둔다
 * (실측 `260px 1082px`). 지역 · 경력 두 축과 적용 버튼, 그리고 현재 직무 표시다.
 *
 * **선택지가 없으면 컨트롤을 비활성으로 둔다.** 누를 수 있는데 아무 일도 없는
 * 셀렉트를 만들지 않는다는 규칙은 그대로다. 다만 선택지가 주어지면(디자인 fixture
 * 또는 조회 API) 실제로 동작한다 — 필터가 결과를 바꾸는 것을 보지 못하면 이 화면의
 * 절반은 디자인할 수 없기 때문이다.
 *
 * 지역·경력 목록은 수집된 공고에서 나오는 값이라 화면이 만들지 않는다. 호출부가
 * 넘기지 않으면 축 이름과 설명만 남는다.
 */
const AXES = [
  { id: 'region', label: '지역', hint: '수집된 공고의 지역이 목록으로 들어옵니다' },
  { id: 'career', label: '경력', hint: '공고가 요구하는 경력 구간이 들어옵니다' },
] as const

export function JobFilterRail({
  region,
  career,
  roleName,
  onChangeRegion,
  onChangeCareer,
  onApply,
  enabled = false,
}: {
  region?: string
  career?: string
  /** 현재 비교 중인 직무 이름. 고르지 않았으면 넘기지 않는다. */
  roleName?: string
  onChangeRegion?: (value: string) => void
  onChangeCareer?: (value: string) => void
  onApply?: () => void
  /** 선택지와 핸들러가 모두 있을 때만 켠다. */
  enabled?: boolean
}) {
  const values: Readonly<Record<string, string | undefined>> = { region, career }
  const handlers: Readonly<Record<string, ((value: string) => void) | undefined>> = {
    region: onChangeRegion,
    career: onChangeCareer,
  }
  const options: Readonly<Record<string, readonly string[]>> = {
    region: JOB_FILTER_OPTIONS.regions,
    career: JOB_FILTER_OPTIONS.careers,
  }

  return (
    <aside className="rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">FILTER</p>

      <div className="mt-4 grid gap-4">
        {AXES.map((axis) => (
          <div key={axis.id}>
            <label
              htmlFor={`filter-${axis.id}`}
              className="text-[12.5px] font-semibold text-brand-ink-soft"
            >
              {axis.label}
            </label>
            <select
              id={`filter-${axis.id}`}
              disabled={!enabled}
              value={values[axis.id] ?? '전체'}
              onChange={(event) => handlers[axis.id]?.(event.target.value)}
              title={enabled ? undefined : '공고 조회 API가 준비되면 사용할 수 있습니다.'}
              className={`mt-1.5 w-full rounded-[10px] border border-brand-line px-3 py-2.5 text-[13px] disabled:cursor-not-allowed ${
                enabled ? 'bg-white text-brand-ink' : 'bg-[#F7F9FC] text-brand-faint'
              }`}
            >
              {enabled ? (
                (options[axis.id] ?? []).map((option) => <option key={option}>{option}</option>)
              ) : (
                <option>전체</option>
              )}
            </select>
            <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-faint">{axis.hint}</p>
          </div>
        ))}
      </div>

      <button
        type="button"
        disabled={!enabled}
        onClick={onApply}
        title={enabled ? undefined : '공고 조회 API가 준비되면 사용할 수 있습니다.'}
        className={`mt-5 w-full rounded-[10px] px-4 py-2.5 text-[13px] font-[750] disabled:cursor-not-allowed ${
          enabled
            ? 'bg-brand-ink text-white'
            : 'border border-brand-line bg-[#F7F9FC] text-brand-faint'
        }`}
      >
        필터 적용
      </button>

      <div className="mt-5 border-t border-brand-line pt-4">
        <p className="text-[12.5px] text-brand-faint">직무</p>
        <p className="mt-1 text-[13.5px] font-[750] text-brand-ink">{roleName ?? '선택 전'}</p>
        <Link
          to="/roles"
          className="mt-1.5 inline-block text-[12.5px] font-semibold text-brand-600 hover:underline"
        >
          {roleName === undefined ? '직무 선택하기' : '직무 변경'}
        </Link>
      </div>
    </aside>
  )
}
