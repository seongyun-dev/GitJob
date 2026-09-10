import { TrendSourceCard } from '@/features/trend/components/TrendSourceCard'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'

/**
 * 기술 트렌드 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `12 Trend Overview`).
 *
 * v2 카드 구조를 유지하되 MVP 출처인 채용공고·GitHub의 두 열만 표시한다.
 * 카드마다 출처 · 상태 · 무엇을 세는지 · 측정 기준 · 순위 목록이 들어간다.
 *
 * **출처를 나란히 두되 합치지 않는다.** 두 출처는 측정 단위와 기간이 달라 순위를
 * 출처 안에서만 비교한다. 종합 Trend 점수를 만들지 않는다.
 *
 * 순위·비중·증감은 집계 API가 준다. 출처마다 상태가 다를 수 있어 따로 받는다.
 */
const SOURCES = [
  {
    source: 'JOB · 채용공고',
    metric: '공고 언급 비중',
    basis: '수집된 공고에서 필수 + 우대로 언급된 비중',
    state: 'PREPARING' as const,
    stateTitle: '집계 준비 중',
    stateDescription: '공고 집계 결과가 준비되면 이 출처의 순위가 채워집니다.',
  },
  {
    source: 'GITHUB',
    metric: '저장소 활동 비중',
    basis: '공개 저장소 활동 기준',
    state: 'PREPARING' as const,
    stateTitle: '집계 준비 중',
    stateDescription: '저장소 활동 집계가 준비되면 이 출처의 순위가 채워집니다.',
  },
] as const

export function TrendPage() {
  return (
    <div>
      <PageHero
        eyebrow="TECHNOLOGY TREND"
        title="기술 트렌드 — 출처별로 따로 봅니다"
        description="채용공고 · GitHub는 측정 단위와 기간이 다릅니다. 출처 안에서만 순위를 비교하고, 합산하거나 종합 점수로 만들지 않습니다."
      />

      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {SOURCES.map((item) => (
          <TrendSourceCard key={item.source} {...item} />
        ))}
      </div>

      <PageFootnote>
        각 출처 안에서만 순위를 비교합니다. 출처 간 순위 차이는 데이터 성격의 차이이며 우열이
        아닙니다. 종합 Trend 점수는 제공하지 않습니다.
      </PageFootnote>
    </div>
  )
}
