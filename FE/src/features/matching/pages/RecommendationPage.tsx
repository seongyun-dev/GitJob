import { Link } from 'react-router'
import { toNextSkills } from '@/features/matching/api/adapter'
import { NextSkillCard } from '@/features/matching/components/NextSkillCard'
import { useRecommendations, useTarget } from '@/features/matching/hooks/useMatching'
import { targetRoleDisplayName } from '@/features/matching/model/targetOptions'
import { activeMatchingJobCount } from '@/features/matching/model/presentation'
import { hasComputedValue } from '@/shared/api/computeState'
import { ComputeStatePanel, PartialNotice } from '@/shared/ui/ComputeStatePanel'
import { DataRegion } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 다음 학습 기술 · 확정 디자인 `Final v2`의 `10 Next Skill Overview`
 * (S15P21E102-279).
 *
 * **정렬 기준은 공고 수 증가분 하나다.** 순위·증감·근거 문장은 전부 C가 계산한
 * 결과이고 화면이 만들지 않는다. 추천 점수라는 값은 계산된 적이 없으므로 표시할
 * 자리도 두지 않는다.
 *
 * 근거 체인(`RecommendationChain`)은 값이 없어도 남긴다. 다섯 단계의 **이름**이
 * "점수가 아니라 근거로 추천한다"는 제품 정의이고, 1순위 카드가 그 단계를 실제
 * 값으로 채운 모습이다.
 */
export function RecommendationPage() {
  const target = useTarget()
  const recommendations = useRecommendations(target.data?.targetKey)

  const data = recommendations.data
  const skills = data === undefined ? [] : toNextSkills(data)
  const first = skills[0]
  const rest = skills.slice(1)
  const ready = hasComputedValue(data)
  const basis = data?.basis
  const jobCount = basis === undefined ? null : activeMatchingJobCount(basis)

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          title="다음에 배울 기술"
          description="배우면 지원할 수 있는 공고가 많이 늘어나는 순서예요."
        />
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {basis !== undefined && jobCount !== null && (
            <div className="rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
              <p className="text-[12px] text-brand-faint">비교 집합</p>
              <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
                {targetRoleDisplayName(basis.targetRole)} 공고 {jobCount}건
              </p>
            </div>
          )}
          <Link
            to="/skill-gap"
            className="gj-clickable rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink"
          >
            ← 부족한 기술
          </Link>
        </div>
      </div>

      <div className="mt-7 grid gap-4">
        <PartialNotice state={data} />

        <ComputeStatePanel
          isLoading={target.isLoading || recommendations.isLoading}
          error={target.error ?? recommendations.error}
          state={data}
          loadingLabel="추천 후보를 불러오는 중입니다."
          onRetry={() => void recommendations.refetch()}
        />

        {ready && (
          /* v2의 `931.8 / 326.2`. 사이드 패널이 후순위 후보 자리다. */
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_326px]">
            <div className="grid gap-4">
              {first === undefined ? (
                <DataRegion title="첫 번째 추천">
                  <StateCard
                    kind="EMPTY"
                    title="추천할 기술이 없어요"
                    description="현재 조건에서 새로 추천할 기술이 없습니다. 부족한 기술과 비교 기준을 다시 확인해 보세요."
                    action={
                      <Link
                        to="/skill-gap"
                        className="gj-clickable inline-flex rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink"
                      >
                        부족한 기술 확인
                      </Link>
                    }
                  />
                </DataRegion>
              ) : (
                <NextSkillCard skill={first} emphasis />
              )}

            </div>

            <div className="grid gap-4">
              <div>
                <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
                  다음 후보
                </p>
                <p className="mt-1.5 text-[12.5px] leading-[1.6] text-brand-muted">
                  지원할 수 있는 공고가 많이 늘어나는 순서입니다.
                </p>
              </div>

              {rest.length === 0 ? (
                <StateCard
                  kind="EMPTY"
                  title="후순위 후보가 없어요"
                  description="현재 조건에서 다른 추천 후보가 없습니다."
                />
              ) : (
                rest.map((skill) => <NextSkillCard key={skill.techId} skill={skill} />)
              )}
            </div>
          </div>
        )}
      </div>

    </div>
  )
}
