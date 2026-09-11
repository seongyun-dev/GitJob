import { RequirementChip } from '@/features/matching/components/RequirementChip'
import type { TargetRoleFixture } from '@/mocks/types'
import { MeterBar } from '@/shared/ui/MeterBar'

/**
 * 직무 카드 · 화면 16 Target Role.
 *
 * 확정 디자인 `Final v2`는 카드마다 넷을 담는다 — 직무 이름 · 비교할 공고 수 ·
 * 현재 필수 전체 충족 수 · 자주 요구되는 기술 대조 목록.
 *
 * 막대의 분모가 **그 직무의 공고 수**인 것이 중요하다. 직무마다 공고 수가 달라
 * (87 · 34 · 29건) 같은 26건이 직무에 따라 다른 길이가 된다. 전체 공고를 분모로
 * 쓰면 직무 간 비교가 되어 버리는데, 이 화면은 직무 안에서의 요구 빈도를 보여준다.
 *
 * 선택 상태를 카드가 스스로 갖지 않는다. 어느 직무를 골랐는지는 화면의 상태이고
 * 카드는 표시만 한다.
 */
export function TargetRoleCard({
  role,
  selected,
  onSelect,
}: {
  role: TargetRoleFixture
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex flex-col rounded-[20px] p-6 text-left transition-colors ${
        selected
          ? 'border-[1.5px] border-brand-600 bg-[linear-gradient(160deg,#FFFFFF,#F7FAFF_70%)] shadow-[0_22px_60px_rgba(56,103,195,0.16)]'
          : 'border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)] hover:border-brand-line-active'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
            {role.kicker}
          </p>
          <h2 className="mt-1.5 text-[20px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            {role.name}
          </h2>
          <p className="mt-1 text-[12.5px] text-brand-faint">{role.summary}</p>
        </div>
        <span
          aria-hidden
          className={`grid size-[26px] shrink-0 place-items-center rounded-full text-[13px] font-black ${
            selected
              ? 'bg-brand-600 text-white'
              : 'border-[1.5px] border-brand-box bg-white text-transparent'
          }`}
        >
          ✓
        </span>
      </div>

      {/* 비교 대상 규모와 현재 결과. 둘을 나란히 둬야 "비교 집합이 바뀐다"가 읽힌다 */}
      <div className="mt-5 grid grid-cols-2 gap-3">
        <div className="rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-3">
          <p className="text-[11.5px] text-brand-faint">비교할 공고</p>
          <p className="mt-1 text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
            {role.jobCount}
            <span className="ml-1 text-[12px] font-semibold text-brand-faint">건</span>
          </p>
        </div>
        <div className="rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-3">
          <p className="text-[11.5px] text-brand-faint">필수 전체 충족 (현재)</p>
          <p
            className={`mt-1 text-[22px] leading-none font-[850] tracking-[-0.04em] ${
              selected ? 'text-brand-600' : 'text-brand-ink-soft'
            }`}
          >
            {role.fullMatchCount}
            <span className="ml-1 text-[12px] font-semibold text-brand-faint">건</span>
          </p>
        </div>
      </div>

      <p className="mt-5 text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
        자주 요구되는 기술 vs 내 EVIDENCE
      </p>
      <ul className="mt-2.5 grid gap-2">
        {role.topSkills.map((skill) => (
          <li key={skill.techName} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
            <div className="min-w-0">
              <p className="truncate text-[12.5px] font-semibold text-brand-ink-soft">
                {skill.techName}
              </p>
              <div className="mt-1.5">
                <MeterBar
                  value={skill.requiredCount}
                  total={role.jobCount}
                  tone={selected ? 'accent' : 'muted'}
                  height={5}
                />
              </div>
            </div>
            <RequirementChip
              requirement={{ techName: skill.levelText, mark: skill.mark }}
            />
          </li>
        ))}
      </ul>

      <p className="mt-5 text-[12.5px] leading-[1.6] text-brand-muted">{role.note}</p>
    </button>
  )
}
