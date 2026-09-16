import { Link, useSearchParams } from 'react-router'
import { toNextSkills, toWhatIfJobs } from '@/features/matching/api/adapter'
import {
  useRecommendations,
  useTarget,
  useWhatIf,
} from '@/features/matching/hooks/useMatching'
import { hasComputedValue } from '@/shared/api/computeState'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { MeterBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * What-if · 확정 디자인 `Final v2`의 `03 What-if` (S15P21E102-279).
 *
 * What-if의 의미는 **"이 기술 Evidence가 요구 Level이 되었다고 가정할 때 기술요건이
 * 매칭되는 공고가 얼마나 늘어나는가"** 다. 합격 가능성 증가가 아니다.
 *
 * <h2>숫자와 목록이 한 응답에서 온다</h2>
 *
 * 증가 건수와 아래 목록이 같은 호출의 결과다. 인수 조건이 "What-if 증가 건수와 신규
 * 부합 공고 목록이 동일한 결과를 사용할 것"이고, 숫자를 추천 API에서 목록을 여기서
 * 읽으면 그 사이에 새 계산이 생겼을 때 둘이 어긋난다. 후보 칩의 `+N`만 추천 응답에서
 * 오는데, 그건 목록이 아니라 탐색용 표시다.
 *
 * 어느 후보를 보는지는 **주소에 실린다**(`?tech=kafka`). 추천 화면에서 넘어온 링크가
 * 그 값을 담고 있고, 새로고침해도 같은 후보가 열려야 하며, 링크를 공유할 수도 있어야
 * 한다. 화면 안 상태로 두면 셋 다 깨진다.
 */
const PER_PAGE = 20

export function WhatIfPage() {
  const [params, setParams] = useSearchParams()

  const target = useTarget()
  const recommendations = useRecommendations(target.data?.targetKey)
  const candidates =
    recommendations.data === undefined ? [] : toNextSkills(recommendations.data)

  const requested = params.get('tech')
  const selected =
    candidates.find((candidate) => candidate.techId === requested) ?? candidates[0]

  const whatIf = useWhatIf(target.data?.targetKey, selected?.techId, {
    page: 1,
    perPage: PER_PAGE,
  })
  const data = whatIf.data
  const jobs = data === undefined ? [] : toWhatIfJobs(data)
  const counts = data?.counts ?? null
  const ready = hasComputedValue(data)

  return (
    <div>
      <Link
        to="/recommendations"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 다음 학습 기술
      </Link>

      <div className="mt-3">
        <PageHero
          eyebrow="NEXT SKILL · WHAT-IF"
          title={
            selected === undefined
              ? '이 기술을 요구 Level로 만들면 무엇이 달라질까요?'
              : `${selected.techName}을(를) 채우면 무엇이 달라질까요?`
          }
          description="공고 매칭과 같은 계산에서, 특정 기술의 Personal Evidence가 요구 Level이 되었다고 가정한 결과입니다."
        />
      </div>

      {/*
        후보 순위 칩. 후보가 없으면 그리지 않는다 -- 누를 것이 없는 탭 줄은 자리만
        차지한다.
      */}
      {candidates.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {candidates.map((candidate) => {
            const active = candidate.techId === selected?.techId
            return (
              <button
                key={candidate.techId}
                type="button"
                aria-pressed={active}
                onClick={() => setParams({ tech: candidate.techId })}
                className={`flex items-center gap-2 rounded-[10px] px-3.5 py-2.5 text-[13px] font-bold transition-colors ${
                  active
                    ? 'bg-tone-accent-bg text-brand-ink'
                    : 'text-brand-faint hover:bg-[#F5F7FA]'
                }`}
              >
                <span className="text-[11px] font-extrabold text-brand-400">
                  #{candidate.rank}
                </span>
                {candidate.techName}
                {candidate.increasedCount !== null && (
                  <span className="text-[12.5px] font-extrabold text-brand-600">
                    +{candidate.increasedCount}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}

      <div className="mt-4 grid gap-4">
        <ComputeStatePanel
          isLoading={target.isLoading || recommendations.isLoading || whatIf.isLoading}
          error={target.error ?? recommendations.error ?? whatIf.error}
          state={data}
          loadingLabel="가정 결과를 불러오는 중입니다."
          onRetry={() => void whatIf.refetch()}
        />

        {selected === undefined && !recommendations.isLoading && (
          <StateCard
            kind="EMPTY"
            title="가정해 볼 후보가 없어요"
            description="추천 후보가 있어야 그 기술을 채웠을 때의 변화를 계산할 수 있습니다."
          />
        )}

        {ready && selected !== undefined && (
          /* v2의 `571 / 757`. 왼쪽이 가정, 오른쪽이 그 결과로 새로 매칭되는 공고다. */
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[571px_minmax(0,1fr)]">
            <DataRegion
              eyebrow={`#${selected.rank} RECOMMENDED`}
              title="무엇을 가정하나"
              hint="Evidence를 실제로 만들지는 않습니다. 같은 계산에서 이 기술만 채웠다고 두고 다시 대조한 결과입니다."
            >
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[22px] leading-[1.2] font-[750] tracking-[-0.03em] text-brand-ink">
                  {selected.techName}
                </h2>
                {selected.fromLevel === null ? (
                  <span className="rounded-lg border border-brand-line bg-white px-2 py-1 text-[11.5px] font-[750] text-brand-faint">
                    현재 미판정
                  </span>
                ) : (
                  <LevelBadge level={selected.fromLevel} />
                )}
              </div>

              {counts === null ? (
                <p className="mt-5 text-[12.5px] leading-[1.7] text-brand-muted">
                  이 후보의 공고 수 변화는 아직 계산되지 않았습니다.
                </p>
              ) : (
                <div className="mt-5">
                  <p className="text-[11.5px] text-brand-faint">
                    필수 기술을 모두 충족하는 공고
                  </p>
                  <div className="mt-2 flex items-end gap-4">
                    <div>
                      <p className="text-[11px] text-brand-faint">현재</p>
                      <p className="text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-ink-soft">
                        {counts.currentCount}
                      </p>
                    </div>
                    <p className="text-[52px] leading-none font-[850] tracking-[-0.05em] text-brand-600">
                      +{counts.increasedCount}
                    </p>
                    <div>
                      <p className="text-[11px] text-brand-faint">확보 후</p>
                      <p className="text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
                        {counts.projectedCount}
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 flex gap-1">
                    <div style={{ flex: Math.max(counts.currentCount, 1) }}>
                      <MeterBar
                        value={counts.currentCount}
                        total={counts.currentCount}
                        tone="muted"
                        height={8}
                      />
                    </div>
                    <div style={{ flex: Math.max(counts.increasedCount, 1) }}>
                      <MeterBar
                        value={counts.increasedCount}
                        total={counts.increasedCount}
                        height={8}
                      />
                    </div>
                  </div>
                </div>
              )}

              {selected.reasons.length > 0 && (
                <>
                  <p className="mt-6 text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
                    추천 근거
                  </p>
                  <ul className="mt-2 grid gap-1.5">
                    {selected.reasons.map((reason) => (
                      <li
                        key={reason}
                        className="flex gap-2 text-[12.5px] leading-[1.6] text-brand-muted"
                      >
                        <span aria-hidden className="text-brand-600">
                          ·
                        </span>
                        {reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </DataRegion>

            <DataRegion
              eyebrow="NEWLY MATCHED"
              title="새로 부합하는 공고"
              hint="이 기술만 채웠을 때 필수 요건을 모두 충족하게 되는 공고입니다. 이미 충족하던 공고는 빠져 있습니다."
            >
              {jobs.length === 0 ? (
                <StateCard
                  kind="EMPTY"
                  title="새로 부합하는 공고가 없어요"
                  description="이 기술을 채워도 필수를 모두 충족하게 되는 공고는 이번 비교 집합에 없습니다."
                />
              ) : (
                <>
                  <ul className="grid gap-2.5">
                    {jobs.map((job) => (
                      <li
                        key={job.id}
                        className="rounded-[14px] border border-brand-line bg-white px-5 py-4"
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <p className="text-[14px] font-[750] tracking-[-0.02em] text-brand-ink">
                            {job.title}
                          </p>
                          {job.sourceUrl !== null && (
                            <a
                              href={job.sourceUrl}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="text-[12px] font-semibold text-brand-600 hover:underline"
                            >
                              원문 보기
                            </a>
                          )}
                        </div>
                        <p className="mt-1 text-[12px] text-brand-faint">{job.meta}</p>
                      </li>
                    ))}
                  </ul>
                  {/*
                    목록 길이와 증가 건수가 같은지 화면이 말한다. 다르면 페이징이
                    잘린 것이고, 그 사실이 보여야 한다.
                  */}
                  <p className="mt-3 text-center text-[12px] text-brand-faint">
                    {data !== undefined && data.hasNext
                      ? `${data.totalCount}건 중 ${jobs.length}건 표시`
                      : `${jobs.length}건 전체 표시`}
                  </p>
                </>
              )}
            </DataRegion>
          </div>
        )}
      </div>

      <PageFootnote>
        공고 수 변화는 합격 가능성이 아닙니다. Evidence를 실제로 만들지 않으며, 같은 비교 집합에서
        그 기술만 요구 Level로 채웠다고 가정한 결과입니다.
      </PageFootnote>
    </div>
  )
}
