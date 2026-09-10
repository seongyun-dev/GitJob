import { Link } from 'react-router'
import { RecommendationChain } from '@/features/matching/components/RecommendationChain'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 다음 학습 기술 · 티켓 S15P21E102-204
 * (확정 디자인 `Final v2`의 `10 Next Skill Overview`).
 *
 * v2 구조: hero(+비교 집합 표시) → `931.8 / 326.2` split(1순위 근거 체인 | 후순위) → 각주.
 * 1순위는 가로 5단으로 펼쳐 무엇을 근거로 추천했는지 보여준다(`RecommendationChain`).
 *
 * **정렬 기준은 공고 수 증가분 하나다.** v2 카피가 "추천 점수는 만들지 않습니다"라고
 * 못 박는다. 순위·증감·근거 문장은 전부 C조 계산 결과이고 조회 API가 develop에 없다.
 * 화면에서 만들어내지 않는다.
 */
export function RecommendationPage() {
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="RECOMMENDATION · NEXT SKILL"
          title="다음에 무엇을 배우면 가장 많이 달라질까요?"
          description="필수 기술을 모두 충족하는 공고 수가 얼마나 늘어나는지로만 정렬합니다. 추천 점수는 만들지 않습니다."
        />
        <Link
          to="/skill-gap"
          className="shrink-0 rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
        >
          ← 부족한 기술
        </Link>
      </div>

      {/* v2의 `931.8 / 326.2`. 사이드 패널이 후순위 후보 자리다. */}
      <div className="mt-7 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_326px]">
        <DataRegion
          eyebrow="#1 RECOMMENDED"
          title="1순위 후보"
          hint="가장 많은 공고가 요구하면서 현재 근거가 부족한 기술입니다."
        >
          <RecommendationChain />
          <div className="mt-3">
            <StateCard
              kind="PREPARING"
              title="추천 결과를 아직 불러올 수 없어요"
              description="학습 후보와 공고 수 변화, 추천 근거를 돌려주는 조회 API가 준비되면 위 다섯 단계에 채워집니다."
            />
          </div>
        </DataRegion>

        <div className="grid gap-4">
          <DataRegion
            eyebrow="OTHERS"
            title="후순위 후보"
            hint="1순위와 같은 기준으로 함께 제시됩니다."
          >
            <StateCard
              kind="PREPARING"
              title="후순위 후보 자리"
              description="반대 신호나 데이터 공백이 있으면 그 사실도 함께 표시합니다."
            />
          </DataRegion>

          <DataRegion
            eyebrow="WHAT-IF"
            title="가정해 보면"
            hint="특정 기술 Evidence가 올라갔다고 가정할 때 무엇이 달라지는지 봅니다."
          >
            <Link
              to="/what-if"
              className="block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-4 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
            >
              What-if 자세히 보기
            </Link>
          </DataRegion>
        </div>
      </div>

      <PageFootnote>
        공고 수 변화는 합격 가능성이 아니라, 해당 기술의 Personal Evidence를 목표 수준으로
        올렸을 때 비교 대상에 들어오는 공고가 얼마나 늘어나는지를 뜻합니다.
      </PageFootnote>
    </div>
  )
}
