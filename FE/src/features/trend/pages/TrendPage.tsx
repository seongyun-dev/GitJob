import { TrendSourceCard } from '@/features/trend/components/TrendSourceCard'
import { useTrendOverview } from '@/features/trend/hooks/useTrends'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { TREND_FOOTNOTE, TREND_SOURCES } from '@/mocks/fixtures/trend'
import type { TrendSourceFixture } from '@/mocks/types'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 기술 트렌드 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `12 Trend Overview`).
 *
 * **출처를 나란히 두되 합치지 않는다.** 출처마다 측정 단위와 기간이 달라 순위를
 * 출처 안에서만 비교한다. 종합 Trend 점수를 만들지 않는다
 * (`docs/ai/c-public-trend.md` 30행).
 *
 * 순위·비중·증감은 집계 API가 준다. 조회 API가 develop에 없어 값은 디자인
 * fixture에서 오며(`VITE_DESIGN_FIXTURES=on`) 출처마다 상태가 다르다.
 *
 * fixture가 와이어프레임과 다른 곳이 하나 있다. Stack Overflow 열은 확정 디자인에
 * 값이 그려져 있지만 데이터 계약은 "Stack Overflow는 현재 입력에 없다"고 적으므로
 * (`docs/ai/c-public-trend.md` 10행) `PREPARING`으로 둔다. 없는 출처를 있는 것처럼
 * 그려 두면 그 전제 위에 화면이 완성된다.
 */
export function TrendPage() {
  const query = useTrendOverview()
  const sources = withDesignFixture<readonly TrendSourceFixture[]>(
    query.data?.sources ?? [],
    () => TREND_SOURCES,
  )

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="TECHNOLOGY TREND"
          title="기술 트렌드 — 출처별로 따로 봅니다"
          description="출처마다 측정 단위와 기간이 다릅니다. 출처 안에서만 순위를 비교하고, 합산하거나 종합 점수로 만들지 않습니다."
        />
        <DesignMockBadge />
      </div>

      {sources.length === 0 ? (
        <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <StateCard
            kind="PREPARING"
            title="집계 준비 중"
            description="채용공고 집계 결과가 준비되면 이 출처의 순위가 채워집니다."
          />
          <StateCard
            kind="PREPARING"
            title="집계 준비 중"
            description="저장소 활동 집계가 준비되면 이 출처의 순위가 채워집니다."
          />
        </div>
      ) : (
        /*
          3열로 둔다. 출처가 셋이고, 두 열로 접으면 마지막 출처가 홀로 남아
          "덜 중요한 출처"로 읽힌다. 좁은 화면에서는 한 열로 쌓인다.
        */
        <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {sources.map((source) => (
            <TrendSourceCard key={source.id} source={source} />
          ))}
        </div>
      )}

      {/*
        단위 범례. 세 막대의 길이가 각 출처 안에서만 상대값이라는 것을 본문 아래에
        한 번 더 밝힌다. v2도 같은 자리에 둔다.
      */}
      {sources.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2">
          {sources.map((source) => (
            <li
              key={source.id}
              className="rounded-full border border-brand-line bg-white/70 px-3 py-1.5 text-[12.5px] font-semibold text-brand-muted"
            >
              {source.unit}
            </li>
          ))}
        </ul>
      )}

      <PageFootnote>
        각 출처 안에서만 순위를 비교합니다. 출처 간 순위 차이는 데이터 성격의 차이이며 우열이
        아닙니다. {TREND_FOOTNOTE}
      </PageFootnote>
    </div>
  )
}
