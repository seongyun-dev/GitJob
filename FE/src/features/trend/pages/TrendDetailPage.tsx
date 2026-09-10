import { Link, useParams } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { SourceLegend } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Trend Detail 초안 · 티켓 S15P21E102-192.
 *
 * 시각 기준: Final `section#trenddetail` — hero → `609 609` 2등분(출처별 카드) → 각주.
 * Final이 출처를 좌우로 나란히 둔 이유가 "Y축·단위·기간이 각각 독립"이라는 규칙이라
 * 그 배치를 그대로 가져왔다.
 *
 * 기간별 추이를 표시하지 않는다. 조회 API가 없고 기간 집계는 FE가 계산하지 않는다.
 */
export function TrendDetailPage() {
  const { techId } = useParams()

  return (
    <div>
      <PageHero
        eyebrow="TREND DETAIL"
        title={techId ?? '기술 트렌드 상세'}
        description="세 출처의 Y축과 단위, 기간은 각각 독립입니다. 하나의 지표로 합치지 않고 출처별로 나란히 보여줍니다."
      />

      {/*
        출처 범례. 이 화면도 출처를 합산하지 않는다는 원칙 위에 있다.
        탭이 아니라 읽기 전용이다. 전환할 데이터가 아직 없다.
      */}
      <div className="mt-7">
        <SourceLegend sources={['채용공고', 'GitHub', 'Stack Overflow']} />
      </div>

      <div className="gj-duo mt-4">
        <DataRegion
          eyebrow="JOB"
          title="채용공고 기준"
          hint="공고 건수와 공고 비중이 이 자리에 들어갑니다."
        >
          <StateCard
            kind="PREPARING"
            title="공고 지표 준비 중"
            description="이 출처의 지표는 곧 제공됩니다. 다른 출처를 먼저 확인할 수 있습니다."
          />
        </DataRegion>

        <DataRegion
          eyebrow="GITHUB"
          title="저장소 활동 기준"
          hint="저장소 활동 지표가 이 자리에 들어갑니다."
        >
          <StateCard
            kind="NO_DATA"
            title="기간 내 데이터가 없어요"
            description="수집된 항목이 없는 것은 오류가 아닙니다. 추정값으로 채우지 않습니다."
          />
        </DataRegion>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          to="/trends"
          className="rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink shadow-[0_10px_28px_rgba(25,47,81,0.07)] hover:border-brand-line-active"
        >
          트렌드 목록
        </Link>
        {techId !== undefined && (
          <Link
            to={`/technologies/${techId}`}
            className="rounded-xl px-4 py-2.5 text-[13px] text-brand-muted hover:text-brand-ink"
          >
            학습 안내 보기
          </Link>
        )}
      </div>

      <PageFootnote>
        종합 Trend 점수는 제공하지 않습니다. 출처마다 READY · PREPARING · NO_DATA 상태가
        따로 표시됩니다.
      </PageFootnote>
    </div>
  )
}
