import { Link, useParams } from 'react-router'
import { GrowthStageCard } from '@/features/trend/components/GrowthStageCard'
import { TrendBarChart } from '@/features/trend/components/TrendBarChart'
import { useTechnologyTrend } from '@/features/trend/hooks/useTrends'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { findGrowthStage } from '@/mocks/fixtures/growthStage'
import { findTechTrend, TREND_FOOTNOTE } from '@/mocks/fixtures/trend'
import type { TechTrendFixture } from '@/mocks/fixtures/trend'
import type { GrowthStageFixture } from '@/mocks/types'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 트렌드 상세 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `13 Trend Detail`).
 *
 * v2 구조: 개요 복귀 링크 → hero → `737.8 / 590.2` split(시계열 | 보조) → 각주.
 *
 * **S6 초안의 성장 단계 카드가 이 화면 최상단에 들어간다.** 초안 부제가 "차트를
 * 보여주는 게 목적이 아니다"이므로 결론(단계)을 먼저 두고 그 근거인 추이를 아래에
 * 둔다. 기술 단위 화면이 이곳뿐이라 별도 라우트를 만들지 않았다.
 *
 * 두 출처의 Y축 · 단위 · 기간은 각각 독립이다. 한 화면에 겹쳐 그리거나 합산하지
 * 않는다. 출처마다 상태가 다를 수 있어(READY · PREPARING · NOT_SUPPORTED) 계열별로
 * 따로 렌더한다.
 *
 * 조회 API가 없어 값은 디자인 fixture에서 온다(`VITE_DESIGN_FIXTURES=on`).
 * 트렌드 개요의 순위에 오르는 기술 전부가 시계열을 갖고 있고 둘 다 `techId`로 찾는다.
 * 개요에 없는 기술로 직접 주소를 치면 못 찾는데, 그건 오류가 아니라 "이 기술의 추이를
 * 아직 불러올 수 없다"는 상태다.
 */
export function TrendDetailPage() {
  const { techId } = useParams()

  const query = useTechnologyTrend(techId)

  /*
   * 성장 단계(S6)에는 조회 API가 **없다** · 티켓 S15P21E102-281.
   *
   * 명세 v0.1의 트렌드 엔드포인트는 개요(`/trends`)·출처별 추세
   * (`/technologies/{techId}/trends`)·후보 비교(`/trends/compare`) 셋뿐이고, 세 축을
   * 묶어 단계를 정하는 규칙 자체가 아직 제품 결정이 아니다. 계약을 지어내지 않고
   * fixture로 남긴다 — 계약 문서 미결에 올렸다. 첫 인수가 계속 `null`인 이유다.
   */
  const stage = withDesignFixture<GrowthStageFixture | null>(null, () =>
    techId === undefined ? null : (findGrowthStage(techId) ?? null),
  )
  const trend = withDesignFixture<TechTrendFixture | undefined>(query.data, () =>
    techId === undefined ? undefined : findTechTrend(techId),
  )

  /*
   * 계열을 출처 순서가 아니라 **값이 있는지**로 나눈다.
   *
   * 앞서는 첫 계열만 차트로 그리고 나머지를 상태 카드로 넘겼는데, 언어(Java ·
   * Python …)는 Innovation Graph에도 실제 분기 데이터가 있어서 그 추이가 화면에서
   * 사라졌다. 기술 종류에 따라 그릴 수 있는 계열 수가 다르다는 것이 이 화면의 사실이다.
   *
   * 차트를 하나로 합치지 않고 계열마다 따로 그린다 — 두 출처의 Y축 · 단위 · 기간이
   * 독립이므로 한 축에 겹치면 비교할 수 없는 것을 비교하게 된다.
   */
  const series = trend?.series ?? []
  const charted = series.filter((item) => item.points.length > 0)
  const stateOnly = series.filter((item) => item.points.length === 0)

  return (
    <div>
      <Link
        to="/trends"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 트렌드 개요
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="TREND DETAIL"
          title={trend?.techName ?? stage?.techName ?? '이 기술의 출처별 추이'}
          description="두 출처의 Y축 · 단위 · 기간은 각각 독립적입니다. 서로 비교하거나 합산하지 마세요."
        />
        <DesignMockBadge />
      </div>

      {/*
        S6 성장 단계. 결론을 먼저 두고 근거 추이를 아래에 둔다. 판정할 수 없는
        기술이면 그 사실을 카드가 말한다.
      */}
      <div className="mt-6">
        <GrowthStageCard stage={stage} />
      </div>

      {/* v2의 `737.8 / 590.2`. 왼쪽이 시계열, 오른쪽이 나머지 출처의 상태다. */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,737fr)_minmax(0,590fr)]">
        <div className="grid gap-4">
          {charted.length === 0 ? (
            <DataRegion
              eyebrow="JOB · 채용공고"
              title="기간별 추이"
              hint="누락된 기간을 보간하지 않습니다. 값이 없는 달은 0이 아니라 없는 것입니다."
            >
              <StateCard
                kind="PREPARING"
                title="추이를 아직 불러올 수 없어요"
                description="기간별 집계가 준비되면 이 영역에 표시합니다. 화면에서 추세를 만들어내지 않습니다."
              />
            </DataRegion>
          ) : (
            charted.map((item) => (
              <DataRegion
                key={item.sourceId}
                eyebrow={item.label}
                title="기간별 추이"
                hint="누락된 기간을 보간하지 않습니다. 값이 없는 기간은 0이 아니라 없는 것입니다."
              >
                <TrendBarChart series={item} />
              </DataRegion>
            ))
          )}
        </div>

        <DataRegion
          eyebrow="OTHER SOURCES"
          title="다른 출처의 상태"
          hint="출처마다 지원 범위와 기간이 달라 따로 표시합니다."
        >
          {stateOnly.length === 0 ? (
            /*
              모든 출처에 값이 있는 경우. `StateCard`를 쓰지 않는다 — 그 컴포넌트의
              값 목록은 "데이터가 없거나 문제가 있는 상태"만 담고 있고, 여기는 그
              어느 것도 아니다. 없는 상태를 만들어 쓰기보다 문장으로 적는다.
            */
            <p className="text-[12.5px] leading-[1.7] text-brand-muted">
              이 기술은 준비된 모든 출처에 값이 있어 왼쪽에 계열별로 표시했습니다. 출처마다
              기간과 단위가 다르므로 서로 비교하거나 합산하지 마세요.
            </p>
          ) : (
            <div className="grid gap-3">
              {stateOnly.map((item) => (
                <div
                  key={item.sourceId}
                  className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-600">
                      {item.label}
                    </p>
                    <span className="rounded-full border border-brand-line bg-white px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] text-brand-faint">
                      {item.status}
                    </span>
                  </div>
                  <p className="mt-2 text-[12.5px] font-semibold text-brand-ink-soft">
                    {item.axisLabel}
                  </p>
                  <p className="mt-1.5 text-[11.5px] leading-[1.6] text-brand-muted">{item.note}</p>
                </div>
              ))}
            </div>
          )}
        </DataRegion>
      </div>

      {/* 단위 범례. 계열마다 무엇을 세는지 한 줄로 남긴다. */}
      {series.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2">
          {series.map((item) => (
            <li
              key={item.sourceId}
              className="rounded-full border border-brand-line bg-white/70 px-3 py-1.5 text-[12.5px] font-semibold text-brand-muted"
            >
              {item.axisLabel}
            </li>
          ))}
        </ul>
      )}

      <PageFootnote>
        {TREND_FOOTNOTE}
        {techId !== undefined && (
          <>
            {' · '}
            기술 <span className="font-evidence text-brand-muted">{techId}</span>
          </>
        )}
      </PageFootnote>
    </div>
  )
}
