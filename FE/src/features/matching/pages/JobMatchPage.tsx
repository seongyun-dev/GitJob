import { useState } from 'react'
import { Link } from 'react-router'
import { JobFilterRail } from '@/features/matching/components/JobFilterRail'
import { JobPostingCard } from '@/features/matching/components/JobPostingCard'
import { JobRequirementDrawer } from '@/features/matching/components/JobRequirementDrawer'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import {
  JOB_MATCH_ALL,
  JOB_MATCH_EMPTY,
  JOB_MATCH_FILTERED,
  JOB_SNAPSHOT_TEXT,
} from '@/mocks/fixtures/jobMatch'
import type { JobMatchScenarioFixture, JobPostingFixture } from '@/mocks/types'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { MeterBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
import type { StatItem } from '@/shared/ui/StatStrip'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 공고 매칭 · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `02 Job Match`).
 *
 * v2 구조: hero(+공고 Snapshot) → 필터 레일 `260 / 1082` → 지표 3연(실측 `332.7 x 3`)
 * → `956/372` split(공고별 기술요건 대조 | 요약 패널) → 각주.
 *
 * 매칭 조회 API가 develop에 없어 값은 디자인 fixture에서 온다. 필터를 바꾸면
 * 시나리오가 바뀌는데, 그것도 fixture다 — 실제 필터링을 화면에서 계산하지 않는다.
 * 대조 결과는 C조 계산이고 FE가 공고를 세지 않는다.
 *
 * **기술요건 충족만 보여준다.** 합격 가능성이나 지원 가능 여부를 판정하지 않는다.
 */

/** 화면이 필터로 시나리오를 고른다. 실제로는 이 자리가 조회 요청이 된다. */
function pickScenario(region: string, career: string): JobMatchScenarioFixture {
  if (region === '지역 전체' && career === '경력 전체') {
    return JOB_MATCH_ALL
  }
  // 결과가 0건인 조합을 하나 남겨 둔다. 빈 상태를 눌러서 확인할 수 없으면
  // 그 화면은 디자인되지 않은 채로 배포된다.
  if (region === '부산' && career === '1~3년') {
    return JOB_MATCH_EMPTY
  }
  return JOB_MATCH_FILTERED
}

function toStats(scenario: JobMatchScenarioFixture | null): readonly StatItem[] {
  return [
    {
      label: '대조한 공고',
      note: scenario === null ? '대조 후 표시' : `${scenario.kpi.total}건`,
      caption: scenario?.kpi.scopeText ?? '선택한 직무의 수집된 공고 전체',
    },
    {
      label: '필수 100% 충족',
      note: scenario === null ? '대조 후 표시' : `${scenario.kpi.fullMatch}건`,
      caption: '모든 필수 기술 보유',
    },
    {
      label: '75~99% 충족',
      note: scenario === null ? '대조 후 표시' : `${scenario.kpi.nearMatch}건`,
      caption: '1개 기술만 더 채우면 되는 구간',
    },
  ]
}

export function JobMatchPage() {
  const [region, setRegion] = useState('지역 전체')
  const [career, setCareer] = useState('경력 전체')
  const [openPosting, setOpenPosting] = useState<JobPostingFixture | null>(null)

  const scenario = withDesignFixture<JobMatchScenarioFixture | null>(null, () =>
    pickScenario(region, career),
  )

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="JOB MATCH"
          title={scenario?.headline ?? '공고 요구 기술과 비교했어요'}
          description="기술요건 충족 여부만 보여줍니다. 합격 가능성이나 지원 가능 여부는 판정하지 않습니다."
        />
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <DesignMockBadge />
          <div className="rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
            <p className="text-[12px] text-brand-faint">공고 Snapshot</p>
            <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
              {scenario === null ? '수집 기준 미정' : JOB_SNAPSHOT_TEXT}
            </p>
          </div>
        </div>
      </div>

      {/* v2의 `260 / 1082` 레일 배치. 좁은 화면에서는 레일이 위로 접힌다. */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <JobFilterRail
          enabled={scenario !== null}
          region={region}
          career={career}
          roleName={scenario === null ? undefined : '백엔드'}
          onChangeRegion={setRegion}
          onChangeCareer={setCareer}
        />

        <div className="grid gap-4">
          <StatStrip items={toStats(scenario)} />

          {/*
            충족 분포 막대. 세 구간을 한 줄에 쌓아 비율을 보여준다. 값이 없을 때는
            그리지 않는다 — 빈 막대는 "0%"라는 다른 사실이 된다.
          */}
          {scenario !== null && scenario.kpi.total > 0 && (
            <div className="rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-[13px] font-[750] text-brand-ink">필수 기술요건 충족 분포</p>
                <p className="text-[11.5px] text-brand-faint">현재 Personal Evidence 기준</p>
              </div>
              <div className="mt-3 flex gap-1.5">
                {[
                  { label: '100% 충족', value: scenario.kpi.fullMatch, tone: 'accent' as const },
                  { label: '75~99%', value: scenario.kpi.nearMatch, tone: 'muted' as const },
                  { label: '75% 미만', value: scenario.kpi.lowMatch, tone: 'warn' as const },
                ].map((band) => (
                  <div key={band.label} style={{ flex: Math.max(band.value, 1) }}>
                    <MeterBar value={band.value} total={band.value} tone={band.tone} height={10} />
                    <p className="mt-2 text-[13px] font-[850] tabular-nums text-brand-ink">
                      {band.value}
                    </p>
                    <p className="truncate text-[11.5px] text-brand-faint">{band.label}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="gj-split">
            <DataRegion
              eyebrow="POSTINGS"
              title="공고별 기술요건 대조"
              hint="✓ 보유 · △ Level 부족 · ✕ Evidence 없음 순으로 공고마다 나란히 표시됩니다."
            >
              {scenario === null ? (
                <StateCard
                  kind="EMPTY"
                  title="비교할 Evidence가 아직 없어요"
                  description="Repository 분석을 마치고 직무를 선택하면 그 결과로 공고 요구 기술과 비교합니다."
                  action={
                    <Link
                      to="/onboarding/repositories"
                      className="inline-block rounded-xl border border-brand-line px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
                    >
                      저장소 선택으로
                    </Link>
                  }
                />
              ) : scenario.postings.length === 0 ? (
                <StateCard
                  kind="EMPTY"
                  title="조건에 맞는 공고가 없어요"
                  description={`${region} · ${career} 조건의 백엔드 공고가 이번 Snapshot에 없습니다. 지역이나 경력 범위를 넓혀보세요.`}
                  action={
                    <button
                      type="button"
                      onClick={() => {
                        setRegion('지역 전체')
                        setCareer('경력 전체')
                      }}
                      className="rounded-xl border border-brand-line px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
                    >
                      전체 공고로 되돌리기
                    </button>
                  }
                />
              ) : (
                <>
                  <div className="grid gap-2.5">
                    {scenario.postings.map((posting) => (
                      <JobPostingCard
                        key={posting.id}
                        posting={posting}
                        onOpen={() => setOpenPosting(posting)}
                      />
                    ))}
                  </div>
                  <p className="mt-3 text-center text-[12px] text-brand-faint">
                    {scenario.moreText}
                  </p>
                </>
              )}
            </DataRegion>

            <div className="grid gap-4">
              <DataRegion
                eyebrow="SKILL GAP"
                title={scenario?.gapTitle ?? '무엇을 비교하나요'}
                hint={
                  scenario === null
                    ? '공고가 적은 요구 기술을 내 Evidence와 기술 단위로 대조합니다.'
                    : `비교 중인 ${scenario.kpi.total}개 공고에서 가장 자주 요구되는 미충족 기술입니다.`
                }
              >
                {scenario === null ? (
                  <dl className="grid gap-3">
                    {[
                      { t: '필수 기술', d: '공고가 반드시 요구하는 기술의 충족 여부' },
                      { t: '우대 기술', d: '있으면 좋은 기술의 충족 여부' },
                      { t: '부족 기술', d: '아직 근거가 없어 다음 학습 후보가 되는 기술' },
                    ].map((item) => (
                      <div key={item.t}>
                        <dt className="text-[13px] font-semibold text-brand-ink">{item.t}</dt>
                        <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                          {item.d}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : scenario.gaps.length === 0 ? (
                  <StateCard
                    kind="EMPTY"
                    title="비교할 공고가 없어요"
                    description="필터를 넓히면 Gap 순위를 다시 계산합니다."
                  />
                ) : (
                  <ol className="grid gap-3">
                    {scenario.gaps.map((gap, index) => (
                      <li key={gap.techName} className="flex items-start gap-3">
                        <span className="mt-0.5 text-[11px] font-extrabold tabular-nums text-brand-faint">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-baseline justify-between gap-2">
                            <p className="truncate text-[13.5px] font-[750] text-brand-ink">
                              {gap.techName}
                            </p>
                            <span className="shrink-0 rounded-lg border border-brand-line bg-[#F5F7FA] px-2 py-1 text-[11px] font-[750] text-brand-muted">
                              {gap.levelText}
                            </span>
                          </div>
                          <p className="mt-1 text-[11.5px] text-brand-faint">
                            필수 요구 {gap.requiredCount}건
                          </p>
                          <div className="mt-1.5">
                            <MeterBar
                              value={gap.requiredCount}
                              total={scenario.gaps[0]?.requiredCount ?? gap.requiredCount}
                              tone={index === 0 ? 'accent' : 'muted'}
                              height={5}
                            />
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                )}

                <Link
                  to="/skill-gap"
                  className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
                >
                  기술별 상세 Gap 보기
                </Link>
                {/* v2는 Gap 보기 바로 아래에 추천 화면 이동을 주 버튼으로 둔다. */}
                <Link
                  to="/recommendations"
                  className="mt-2.5 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
                >
                  다음 기술 추천 보기
                </Link>

                {scenario !== null && (
                  <p className="mt-3 text-[11.5px] leading-[1.6] text-brand-faint">
                    Gap은 현재 공고 집합 기준으로 다시 계산됩니다. 필터를 바꾸면 순위도 바뀝니다.
                  </p>
                )}
              </DataRegion>
            </div>
          </div>
        </div>
      </div>

      <JobRequirementDrawer posting={openPosting} onClose={() => setOpenPosting(null)} />

      <PageFootnote>
        기술요건 충족도만 보여줍니다. 합격 가능성이나 취업 확률은 계산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
