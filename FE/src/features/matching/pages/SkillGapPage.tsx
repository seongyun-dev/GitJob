import { Link } from 'react-router'
import { toSkillGapGroups, toSkillGapSummary } from '@/features/matching/api/adapter'
import { SkillGapRows, SKILL_GAP_TEMPLATE } from '@/features/matching/components/SkillGapRows'
import { useSkillGap, useTarget } from '@/features/matching/hooks/useMatching'
import { hasComputedValue } from '@/shared/api/computeState'
import { ComputeStatePanel, PartialNotice } from '@/shared/ui/ComputeStatePanel'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Skill Gap · 확정 디자인 `Final v2`의 `17 Skill Gap` (S15P21E102-279).
 *
 * 이 화면이 답하는 질문은 **"무엇이 부족한가"** 하나다. "그럼 무엇을 먼저 배울까"는
 * 다음 화면(Next Skill / What-if)의 몫이라 여기서 순위를 매기지 않는다.
 *
 * **총점 · 취업 확률 · 역량 점수 · 부족도 %를 쓰지 않는다.** 사용자가 다음 행동으로
 * 옮길 수 있는 보완 기술만 남기고 내부 판정 상태표는 보여주지 않는다.
 *
 * 마지막 열은 추천 기술이 언급된 공고 수다. 상위 후보에만 있는 값이라 대부분의
 * 행은 `—`다.
 */
const GAP_COLUMNS = ['기술', '필수 요구', '우대 요구', '내 수준', '판정', '관련 공고'] as const

export function SkillGapPage() {
  const target = useTarget()
  const skillGap = useSkillGap(target.data?.targetKey)

  const data = skillGap.data
  const groups =
    data === undefined
      ? []
      : toSkillGapGroups(data.rows).filter(
          (group) => group.verdict === 'LEVEL_SHORT' || group.verdict === 'NO_EVIDENCE',
        )
  const summary = data === undefined ? null : toSkillGapSummary(data)
  const ready = hasComputedValue(data)

  return (
    <div>
      <Link
        to="/jobs"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 공고 매칭
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero title="부족한 기술" />
        {summary !== null && (
          <div className="shrink-0 rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
            <p className="text-[12px] text-brand-faint">비교 집합</p>
            <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
              {summary.basisText}
            </p>
          </div>
        )}
      </div>

      <div className="mt-7 grid gap-4">
        <PartialNotice state={data} />

        <ComputeStatePanel
          isLoading={target.isLoading || skillGap.isLoading}
          error={target.error ?? skillGap.error}
          state={data}
          loadingLabel="기술별 대조 결과를 불러오는 중입니다."
          onRetry={() => void skillGap.refetch()}
        />

        {ready && (
          <>
            <div>
              {groups.length === 0 ? (
                <StateCard
                  kind="EMPTY"
                  title="현재 확인된 부족한 기술이 없어요"
                  description="현재 확인된 결과에는 보완 대상으로 확정된 기술이 없습니다."
                />
              ) : (
                <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
                  <div
                    className="hidden gap-4 border-b border-brand-line px-[22px] py-3 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
                    style={{ gridTemplateColumns: SKILL_GAP_TEMPLATE }}
                  >
                    {GAP_COLUMNS.map((label) => (
                      <span key={label} className="truncate">
                        {label}
                      </span>
                    ))}
                  </div>
                  <div className="p-4">
                    <SkillGapRows groups={groups} />
                  </div>
                  <p className="border-t border-brand-line px-[22px] py-3 text-[11.5px] leading-[1.65] text-brand-faint">
                    상위 추천 기술의 관련 공고 수입니다.
                  </p>
                </div>
              )}

            </div>
          </>
        )}
      </div>

    </div>
  )
}
