import { Link } from 'react-router'
import { toNextSkills } from '@/features/matching/api/adapter'
import { DataGapNotice } from '@/features/matching/components/DataGapNotice'
import { NextSkillCard } from '@/features/matching/components/NextSkillCard'
import { RecommendationChain } from '@/features/matching/components/RecommendationChain'
import { useRecommendations, useTarget } from '@/features/matching/hooks/useMatching'
import { hasComputedValue } from '@/shared/api/computeState'
import { ComputeStatePanel, PartialNotice } from '@/shared/ui/ComputeStatePanel'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
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

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="RECOMMENDATION · NEXT SKILL"
          title="다음에 무엇을 배우면 가장 많이 달라질까요?"
          description="필수 기술을 모두 충족하는 공고 수가 얼마나 늘어나는지로만 정렬합니다. 추천 점수는 만들지 않습니다."
        />
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {basis !== undefined && basis.jobCount !== null && (
            <div className="rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
              <p className="text-[12px] text-brand-faint">비교 집합</p>
              <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
                {basis.targetRole ?? '선택한 직무'} 수요 산정 공고 {basis.jobCount}건
              </p>
            </div>
          )}
          <Link
            to="/skill-gap"
            className="rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
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
                <DataRegion
                  eyebrow="#1 RECOMMENDED"
                  title="1순위 후보"
                  hint="가장 많은 공고가 요구하면서 현재 근거가 부족한 기술입니다."
                >
                  <StateCard
                    kind="EMPTY"
                    title="추천할 기술이 없어요"
                    description="요구 기술을 이미 충족했거나, 선행 조건이 갖춰진 후보가 없습니다. 화면에서 순위를 만들지 않습니다."
                  />
                </DataRegion>
              ) : (
                <NextSkillCard skill={first} emphasis />
              )}

              {/*
                근거 체인. 1순위 카드가 값을 채워도 이 골격을 남기는 이유는 다섯
                단계가 추천의 정의이고, 카드가 그중 일부만 보여주기 때문이다.
              */}
              <DataRegion
                eyebrow="WHY"
                title="무엇을 근거로 추천하나요"
                hint="다섯 단계를 모두 밝힙니다. 하나의 점수로 합치지 않습니다."
              >
                <RecommendationChain />
              </DataRegion>
            </div>

            <div className="grid gap-4">
              <div>
                <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
                  다음 후보
                </p>
                <p className="mt-1.5 text-[12.5px] leading-[1.6] text-brand-muted">
                  같은 기준 · 필수 전체 충족 공고 증가 수 순
                </p>
              </div>

              {rest.length === 0 ? (
                <StateCard
                  kind="EMPTY"
                  title="후순위 후보가 없어요"
                  description="C는 상위 후보만 계산합니다. 더 많은 후보가 생기면 이 자리에 놓입니다."
                />
              ) : (
                rest.map((skill) => <NextSkillCard key={skill.techId} skill={skill} />)
              )}

              {data !== undefined && <DataGapNotice gaps={data.dataGaps} />}
            </div>
          </div>
        )}
      </div>

      <PageFootnote>
        공고 수 변화는 합격 가능성이 아닙니다. 추천 점수나 순위 점수를 만들지 않으며, 정렬 기준은
        필수 기술을 모두 충족하는 공고 수의 증가분 하나입니다.
      </PageFootnote>
    </div>
  )
}
