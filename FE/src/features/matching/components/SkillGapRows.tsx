import type {
  SkillGapGroupView,
  SkillGapRowView,
  SkillGapVerdict,
} from '@/features/matching/model/view'
import { formatImpactIncrease } from '@/features/matching/components/ConditionImpactSummary'
import { LevelBadge } from '@/shared/ui/LevelBadge'

/**
 * 기술별 Gap 표의 본문 · 화면 17 Skill Gap.
 *
 * 확정 디자인 `Final v2`가 판정별로 네 묶음을 만든다. 묶음을 없애고 배지로만
 * 구분하면 이 화면의 주제("점수가 아니라 구분")가 사라진다.
 *
 * **`판단 근거 부족`을 부족과 섞지 않는 것이 규칙이다.** 선언(L0)만 확인된 기술은
 * 사용 여부를 판정하지 않았을 뿐이라 Gap 집계에서 빠진다. 관련 공고 건수는
 * 추천 상위 후보에만 계산한다(`null`은 미계산).
 */
export const SKILL_GAP_TEMPLATE = '82px 200px 120px 160px 150px 110px'

/** 판정별 표시. 색은 톤 토큰을 쓰고 기호를 함께 둬 색만으로 구분하지 않는다. */
const VERDICT_STYLE: Readonly<Record<SkillGapVerdict, { mark: string; className: string }>> = {
  MET: { mark: '✓', className: 'bg-tone-success-bg text-tone-success' },
  LEVEL_SHORT: { mark: '△', className: 'bg-tone-caution-bg text-tone-caution' },
  NO_EVIDENCE: { mark: '✕', className: 'border border-brand-line bg-white text-brand-faint' },
  UNDETERMINED: { mark: '?', className: 'bg-tone-neutral-bg text-tone-neutral' },
}

/** 판정 배지. 표와 지표 모달이 같은 얼굴로 같은 판정을 말하게 한다. */
export function VerdictBadge({ row }: { row: SkillGapRowView }) {
  const style = VERDICT_STYLE[row.verdict]
  return (
    <span
      className={`inline-flex w-fit items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] font-[750] ${style.className}`}
    >
      <span aria-hidden className="font-black">
        {style.mark}
      </span>
      {row.verdictText}
    </span>
  )
}

function GapRow({ row }: { row: SkillGapRowView }) {
  return (
    <div
      className="grid items-center gap-4 rounded-[12px] px-[10px] py-2.5 max-lg:grid-cols-2"
      style={{ gridTemplateColumns: SKILL_GAP_TEMPLATE }}
    >
      <p className="truncate text-[13px] font-[750] text-brand-ink max-lg:col-span-2">
        {row.techName}
      </p>
      {/* 수요 집계에 없는 기술은 0건이 아니라 `—`다. 요구가 없는 것과 모르는 것은 다르다 */}
      <p className="text-[12.5px] tabular-nums text-brand-muted">
        {row.requiredCount === null ? '—' : `${row.requiredCount}건`}
      </p>
      {/* 우대 요구가 아예 없는 행은 0이 아니라 `—`다. 0건과 구분한다 */}
      <p className="text-[12.5px] tabular-nums text-brand-faint">
        {row.preferredCount === null ? '—' : `${row.preferredCount}건`}
      </p>
      <div>
        {row.personalLevel === null ? (
          <span className="text-[12.5px] text-brand-faint">없음</span>
        ) : (
          <LevelBadge level={row.personalLevel} />
        )}
      </div>
      <VerdictBadge row={row} />
      <p
        className={`text-[13px] font-[850] tabular-nums ${
          row.fillDelta === null || row.fillDelta === 0 ? 'text-brand-faint' : 'text-brand-600'
        }`}
      >
        {row.fillDelta === null ? '—' : formatImpactIncrease(row.fillDelta)}
      </p>
    </div>
  )
}

export function SkillGapRows({ groups }: { groups: readonly SkillGapGroupView[] }) {
  return (
    <div className="grid gap-1">
      {groups.map((group) => (
        <section key={group.verdict}>
          <div className="flex flex-wrap items-center gap-2.5 px-[10px] pt-4 pb-2">
            <p className="text-[12px] font-extrabold tracking-[0.06em] text-brand-ink-soft">
              {group.title}
            </p>
            <p className="min-w-0 flex-1 truncate text-[11.5px] text-brand-faint">
              {group.description}
            </p>
            <span className="shrink-0 rounded-full bg-tone-neutral-bg px-2.5 py-1 text-[11px] font-extrabold text-tone-neutral">
              {group.rows.length}개
            </span>
          </div>
          <div className="divide-y divide-[#F1F4F9]">
            {group.rows.map((row) => (
              <GapRow key={row.techName} row={row} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
