import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { AnalysisStepList } from '@/features/analysis/components/AnalysisStepList'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import type { AnalysisProgressFixture } from '@/mocks/fixtures/analysisFlow'
import {
  ANALYSIS_PARTIAL_NOTE,
  ANALYSIS_PARTIAL_RESULT,
  ANALYSIS_RATE_LIMITED,
  ANALYSIS_REPO_PROGRESS,
  ANALYSIS_RUNNING,
  ANALYSIS_STEPS,
} from '@/mocks/fixtures/analysisFlow'
import type { AnalysisStepFixture } from '@/mocks/types'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { JobStatus } from '@/shared/ui/JobStatus'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { MeterBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 분석 진행 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `07 Analysis Progress`).
 *
 * v2 구조: hero → 진행 영역(단계 4칸) + 우측 `PARTIAL RESULT` 패널(958/372).
 *
 * 상태 조회 API가 develop에 없어(S15P21E102-133 진행 중) 값은 디자인 fixture에서
 * 온다(`VITE_DESIGN_FIXTURES=on`). 꺼져 있으면 단계 이름만 남는다.
 *
 * **`RATE_LIMITED`를 실패로 그리지 않는 것이 이 화면의 규칙이다.** 종료 상태가
 * 아니므로(`isTerminalJobStatus`) 진행률이 유지되고 부분 결과도 남는다. 두 상태를
 * 나란히 볼 수 있게 전환 버튼을 두었는데, 이건 fixture가 있을 때만 나오는 디자인
 * 도구다 — 제품 컨트롤이 아니므로 실제 API가 붙으면 지운다.
 *
 * URL의 `analysisId`는 실제 route state지만 화면의 주요 정보가 아니라 각주로 둔다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-136(이윤서)에 있다. 시각 적용까지만 한다.
 */
export function AnalysisProgressPage() {
  const { analysisId } = useParams()
  const [rateLimited, setRateLimited] = useState(false)

  const steps = withDesignFixture<readonly AnalysisStepFixture[] | undefined>(
    undefined,
    () => ANALYSIS_STEPS,
  )
  const progress = withDesignFixture<AnalysisProgressFixture | null>(null, () =>
    rateLimited ? ANALYSIS_RATE_LIMITED : ANALYSIS_RUNNING,
  )

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="ANALYSIS"
          title={progress?.title ?? 'GitHub를 분석하고 있어요'}
          description="선택한 Repository를 순서대로 분석합니다. 이 화면을 벗어나도 분석은 계속됩니다."
        />
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <DesignMockBadge />
          {progress !== null && (
            <div className="flex gap-1.5 rounded-[12px] bg-[#F5F7FA] p-1">
              {[
                { label: '진행 중', value: false },
                { label: 'RATE_LIMITED', value: true },
              ].map((item) => (
                <button
                  key={item.label}
                  type="button"
                  aria-pressed={rateLimited === item.value}
                  onClick={() => setRateLimited(item.value)}
                  className={`rounded-[9px] px-3.5 py-2 text-[12.5px] transition-colors ${
                    rateLimited === item.value
                      ? 'bg-white font-[750] text-brand-ink shadow-[0_3px_10px_rgba(25,48,80,0.08)]'
                      : 'font-semibold text-brand-faint'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="gj-split mt-7">
        <div className="grid gap-4">
          {/* 전체 진행률. 값이 없으면 이 블록을 그리지 않는다 — 0%는 다른 사실이다 */}
          {progress !== null && (
            <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-[12px] text-brand-faint">전체 진행률</p>
                  <p className="mt-1 text-[34px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
                    {progress.progressPercent}
                    <span className="text-[16px] font-bold text-brand-faint">%</span>
                  </p>
                </div>
                <JobStatus status={progress.status} />
              </div>
              <div className="mt-3">
                <MeterBar
                  value={progress.progressPercent}
                  total={100}
                  tone={progress.status === 'RATE_LIMITED' ? 'warn' : 'accent'}
                  height={10}
                />
              </div>
              <p className="mt-2.5 text-[12.5px] text-brand-muted">{progress.statusText}</p>

              {/*
                한도 대기 배너. 실패가 아니라는 것과 부분 결과가 유지된다는 것을
                같은 자리에서 말한다.
              */}
              {progress.banner !== null && (
                <div className="mt-4">
                  <StateCard
                    kind="RATE_LIMITED"
                    title="GitHub 호출 한도를 기다리고 있어요"
                    description={progress.banner}
                    meta="14:25"
                  />
                </div>
              )}

              <div className="mt-4 border-t border-brand-line pt-4">
                <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
                  REPOSITORY CONTEXT
                </p>
                <ul className="mt-2.5 grid gap-2">
                  {ANALYSIS_REPO_PROGRESS.map((repo) => (
                    <li
                      key={repo.name}
                      className="flex items-center gap-3 rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-2.5"
                    >
                      <span
                        className={`grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-extrabold ${
                          repo.state === 'DONE'
                            ? 'bg-tone-success-bg text-tone-success'
                            : repo.state === 'RUNNING'
                              ? 'bg-tone-accent-bg text-tone-accent'
                              : 'bg-tone-neutral-bg text-tone-neutral'
                        }`}
                      >
                        {repo.state === 'DONE' ? '✓' : ''}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-[750] text-brand-ink">
                          {repo.name}
                        </p>
                        <p className="mt-0.5 truncate text-[11.5px] text-brand-faint">
                          {repo.meta}
                        </p>
                      </div>
                      <span className="shrink-0 text-[11.5px] font-semibold text-brand-muted">
                        {repo.statusText}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          <DataRegion
            eyebrow="PROGRESS"
            title="분석 단계"
            hint="네 단계를 순서대로 거칩니다. Dependency → 설정 → 구현 순으로 Level을 판정합니다."
          >
            <AnalysisStepList steps={steps} />
            {steps === undefined && (
              <div className="mt-3">
                <StateCard
                  kind="PREPARING"
                  title="진행 상태를 아직 조회할 수 없어요"
                  description="단계별 진행과 처리 대상 수를 돌려주는 조회 API가 준비되면 위 단계에 표시됩니다. 접수된 분석은 서버에서 계속 진행됩니다."
                />
              </div>
            )}
          </DataRegion>
        </div>

        <aside className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            PARTIAL RESULT
          </p>
          <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            지금까지 확인된 기술
          </h2>
          <div className="mt-4">
            {progress === null ? (
              <StateCard
                kind="PREPARING"
                title="중간 결과 준비 중"
                description="분석이 진행되는 동안 확인된 기술이 이 자리에 쌓입니다. 추정값으로 채우지 않습니다."
              />
            ) : (
              /*
                Repository Level만 보여준다. 완료 화면(08)의 표와 같은 컴포넌트를
                쓰고 싶어지는 자리인데, 저쪽은 Personal · Repository 두 축이고
                여기는 아직 한 축이라 그대로 쓰면 축이 혼동된다.
              */
              <ul className="grid gap-2">
                {ANALYSIS_PARTIAL_RESULT.map((item) => (
                  <li
                    key={item.techName}
                    className="flex items-center justify-between gap-3 rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-2.5"
                  >
                    <span className="truncate text-[13px] font-[750] text-brand-ink">
                      {item.techName}
                    </span>
                    <LevelBadge level={item.repoLevel} variant="repository" />
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className="mt-4 text-[12.5px] leading-[1.6] text-brand-muted">
            {progress === null
              ? 'Personal Level은 사용자 기여 확인 단계가 끝나야 확정됩니다. 중간 결과는 Repository 기준입니다.'
              : ANALYSIS_PARTIAL_NOTE}
          </p>
          <Link
            to="/evidence"
            className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            Evidence 화면 보기
          </Link>
          <Link
            to="/onboarding/repositories"
            className="mt-2 block rounded-xl px-4 py-2.5 text-center text-[13px] text-brand-muted hover:text-brand-ink"
          >
            저장소 다시 선택
          </Link>
        </aside>
      </div>

      {analysisId !== undefined && (
        <PageFootnote>
          분석 ID <span className="font-evidence text-brand-muted">{analysisId}</span> · 이 화면을
          벗어나도 분석은 서버에서 계속 진행됩니다.
        </PageFootnote>
      )}
    </div>
  )
}
