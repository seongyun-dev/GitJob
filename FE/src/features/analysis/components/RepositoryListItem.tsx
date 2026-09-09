import type { RepositorySummary } from '@/features/analysis/api/types'
import { RepositoryStateBadge } from '@/features/analysis/components/RepositoryStateBadge'

/**
 * 저장소 카드 · 티켓 S15P21E102-117.
 *
 * 치수·색은 `GitJob Desktop UI Final.html`의 Repository Selection 카드
 * computed style을 그대로 옮겼다.
 *   height 79px · padding 18px 20px · radius 18px · flex/center/gap 16px
 *   background 흰색 고정 · shadow rgba(25,47,81,0.07) 0 10px 28px
 *   border 1px — 미선택 #E0E7F1 / 선택 #CFE0FF
 *   이름 17px/750/ls -0.425px #101A2E · 메타 13px #5F6F86 · 우측 12.5px #7C8A9E
 *
 * 선택 표시가 배경 tint가 아니라 **테두리 색과 checkbox**인 점이 Final의 핵심이다.
 * 카드 배경을 파랗게 칠하면 목록 전체가 얼룩덜룩해진다.
 *
 * checkbox는 Final처럼 22px/radius 7px 커스텀 박스로 보이게 하되 실제 요소는
 * 네이티브 `input[type=checkbox]`를 유지한다. `sr-only`로 숨기고 형제 span을
 * `peer-checked:`로 칠하는 방식이라 키보드 포커스·Space 토글·label 클릭이 그대로 동작한다.
 *
 * 제목에 `name`이 아니라 `fullName`을 쓴다. 요청 본문에 실리는 식별자가 `fullName`이라
 * 사용자가 보는 값과 서버로 가는 값이 같아야 오분석을 확인할 수 있다. 긴 이름은
 * 자르지 않고 접는다. 잘라 버리면 어떤 저장소를 보낼지 확인할 수 없다.
 *
 * Final 우측의 `최근 push N일 전`은 `pushed_at` 기준이지만 BE 응답에는 그 필드가 없다
 * (`RepositorySummaryResponse`는 `updatedAt`만 준다). 없는 값을 만들지 않고 우리가
 * 가진 `updatedAt`을 같은 자리에 같은 형식으로 두되 문구를 "갱신"으로 정확히 쓴다.
 */

const RELATIVE = new Intl.RelativeTimeFormat('ko-KR', { numeric: 'auto' })

const UNITS: ReadonlyArray<{ unit: Intl.RelativeTimeFormatUnit; ms: number }> = [
  { unit: 'year', ms: 365 * 24 * 60 * 60 * 1000 },
  { unit: 'month', ms: 30 * 24 * 60 * 60 * 1000 },
  { unit: 'week', ms: 7 * 24 * 60 * 60 * 1000 },
  { unit: 'day', ms: 24 * 60 * 60 * 1000 },
  { unit: 'hour', ms: 60 * 60 * 1000 },
]

/** BE는 GitHub의 ISO 문자열을 그대로 넘긴다. 파싱 실패 시 줄을 빼고 날짜를 만들지 않는다. */
function formatUpdatedAt(iso: string): string | null {
  const parsed = Date.parse(iso)
  if (Number.isNaN(parsed)) {
    return null
  }
  const diff = parsed - Date.now()
  for (const { unit, ms } of UNITS) {
    if (Math.abs(diff) >= ms) {
      return RELATIVE.format(Math.round(diff / ms), unit)
    }
  }
  return RELATIVE.format(0, 'hour')
}

export function RepositoryListItem({
  repository,
  selected,
  onToggle,
}: {
  repository: RepositorySummary
  selected: boolean
  onToggle: (fullName: string) => void
}) {
  const disabled = !repository.analyzable
  const updatedAt = formatUpdatedAt(repository.updatedAt)
  const meta = [repository.language, repository.defaultBranch].filter(
    (entry): entry is string => entry !== null,
  )

  return (
    <li>
      <label
        className={`flex items-center gap-4 rounded-[18px] border bg-white px-5 py-[18px] shadow-[0_10px_28px_rgba(25,47,81,0.07)] transition-colors ${
          disabled
            ? 'cursor-not-allowed border-brand-line'
            : `cursor-pointer ${selected ? 'border-brand-line-active' : 'border-brand-line hover:border-brand-line-active'}`
        }`}
      >
        <input
          type="checkbox"
          className="peer sr-only"
          value={repository.fullName}
          checked={selected}
          disabled={disabled}
          onChange={() => onToggle(repository.fullName)}
        />
        <span
          aria-hidden="true"
          className="grid size-[22px] shrink-0 place-items-center rounded-[7px] border border-brand-box bg-white text-[12px] leading-none font-extrabold text-transparent peer-checked:border-transparent peer-checked:bg-[linear-gradient(135deg,var(--color-brand-600),var(--color-brand-400))] peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-brand-600/45 peer-disabled:bg-neutral-100"
        >
          ✓
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span
              className={`text-[17px] leading-[1.2] font-[750] tracking-[-0.025em] break-all ${
                disabled ? 'text-brand-faint' : 'text-brand-ink'
              }`}
            >
              {repository.fullName}
            </span>
            {repository.isPrivate && <RepositoryStateBadge state="PRIVATE" />}
            {disabled && <RepositoryStateBadge state="UNANALYZABLE" />}
          </span>
          <span className="mt-1.5 block text-[13px] text-brand-muted">{meta.join(' · ')}</span>
        </span>

        {updatedAt !== null && (
          <span className="hidden shrink-0 text-[12.5px] whitespace-nowrap text-brand-faint sm:block">
            {updatedAt} 갱신
          </span>
        )}
      </label>
    </li>
  )
}
