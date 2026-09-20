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
 * <h2>왜 3열 한 줄인가 (S15P21E102-364)</h2>
 *
 * 이 화면은 `1순위 + 사이드 패널(326px 고정)` 2열이었다. 왼쪽 열에는 카드가 하나뿐인데
 * 오른쪽 열은 소제목 + 카드 둘이라 더 길었고, grid 기본값 `align-items: stretch`가
 * 1순위 카드를 오른쪽 열 높이까지 늘렸다. 카드 아래 절반이 비어 보이던 것이 그
 * 결과이고, 동시에 2·3순위는 326px 안에서 근거 문장이 두 단어마다 접혔다.
 *
 * 그래서 `index.css`의 `.gj-trio`로 돌아간다. `463 370 370`(Final의 nextskill)에서 온
 * 규칙이고 `align-items: start`를 갖고 있어 카드 높이를 내용이 정한다. 배치를 화면에
 * 인라인으로 적지 않는 이유는 그 파일 위쪽 주석과 같다 — 큰 화면 보완을 화면마다
 * 반복하지 않는다.
 *
 * 비교 집합과 되돌아가기는 `PageHero`의 `aside` 자리로 옮겼다. 본문보다 큰 상자를
 * 세워 둘 값이 아니다.
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
      <PageHero
        title="다음에 배울 기술"
        description="배우면 필수 기술을 모두 충족하는 공고가 많이 늘어나는 순서예요."
        aside={
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {basis !== undefined && jobCount !== null && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-line bg-white px-3.5 py-2 text-[12.5px] font-[750] text-brand-ink-soft">
                {targetRoleDisplayName(basis.targetRole)}
                <span aria-hidden className="text-brand-faint">
                  ·
                </span>
                공고 {jobCount.toLocaleString('ko-KR')}건
              </span>
            )}
            {/* 되돌아가기는 보조 행동이다. 본문 카드와 같은 무게로 세우지 않는다. */}
            <Link
              to="/skill-gap"
              className="gj-clickable rounded-full border border-brand-line bg-white px-3.5 py-2 text-[12.5px] font-semibold text-brand-muted"
            >
              ← 부족한 기술
            </Link>
          </div>
        }
      />

      <div className="mt-6 grid gap-4">
        <PartialNotice state={data} compact />

        <ComputeStatePanel
          isLoading={target.isLoading || recommendations.isLoading}
          error={target.error ?? recommendations.error}
          state={data}
          loadingLabel="추천 후보를 불러오는 중입니다."
          onRetry={() => void recommendations.refetch()}
        />

        {ready &&
          (first === undefined ? (
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
            /* v2의 `463 370 370`. 1순위가 넓되 2·3순위를 눌러 앉히지는 않는다. */
            <div className="gj-trio">
              {skills.map((skill) => (
                <NextSkillCard
                  key={skill.techId}
                  skill={skill}
                  emphasis={skill.techId === first.techId}
                />
              ))}

              {/*
                후순위가 없다는 것도 결과다. 빈 칸으로 두면 카드가 덜 그려진 것처럼
                보이므로 같은 줄에서 그 사실을 말한다.
              */}
              {rest.length === 0 && (
                <StateCard
                  kind="EMPTY"
                  title="후순위 후보가 없어요"
                  description="현재 조건에서 다른 추천 후보가 없습니다."
                />
              )}
            </div>
          ))}
      </div>
    </div>
  )
}
