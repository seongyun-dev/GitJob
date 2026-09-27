import { Link, useSearchParams } from 'react-router'
import { toNextSkills, toWhatIfJobs } from '@/features/matching/api/adapter'
import { ConditionImpactSummary, formatImpactIncrease } from '@/features/matching/components/ConditionImpactSummary'
import {
  useRecommendations,
  useTarget,
  useWhatIf,
} from '@/features/matching/hooks/useMatching'
import { hasComputedValue } from '@/shared/api/computeState'
import {
  defaultWhatIfImpactKind,
  type WhatIfImpactKind,
} from '@/features/matching/model/whatIfNavigation'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { DataRegion } from '@/shared/ui/DataRegion'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { PageHero } from '@/shared/ui/PageHero'
import { ReasonsDisclosure } from '@/shared/ui/ReasonsDisclosure'
import { StateCard } from '@/shared/ui/StateCard'
import type { NextSkillEvidenceStatus } from '@/features/matching/model/view'

/**
 * What-if · 확정 디자인 `Final v2`의 `03 What-if` (S15P21E102-279).
 *
 * 현행 What-if는 추천 기술이 필수 또는 우대로 언급된 공고를 보여 준다.
 *
 * <h2>숫자와 목록이 한 응답에서 온다</h2>
 *
 * 필수·우대·합집합 건수와 아래 목록이 같은 호출의 결과다. 후보 칩만 추천 응답에서
 * 오며 탐색용 표시다. 마감 여부가 두 호출 사이에 달라질 수 있으므로 상세 수치가
 * 해당 목록의 권위 있는 값이다.
 *
 * 어느 후보를 보는지는 **주소에 실린다**(`?tech=kafka`). 추천 화면에서 넘어온 링크가
 * 그 값을 담고 있고, 새로고침해도 같은 후보가 열려야 하며, 링크를 공유할 수도 있어야
 * 한다. 화면 안 상태로 두면 셋 다 깨진다.
 */
const PER_PAGE = 20

const EVIDENCE_LABEL: Readonly<Partial<Record<NextSkillEvidenceStatus, string>>> = {
  NOT_HELD: '미보유',
  PERSONAL_LEVEL_UNKNOWN: '내 수준 미판정',
}

export function WhatIfPage() {
  const [params, setParams] = useSearchParams()

  const target = useTarget()
  const recommendations = useRecommendations(target.data?.targetKey)
  const candidates =
    recommendations.data === undefined ? [] : toNextSkills(recommendations.data)

  const requested = params.get('tech')
  const requestedPage = Number(params.get('page') ?? '1')
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1
  const selected =
    candidates.find((candidate) => candidate.techId === requested) ?? candidates[0]
  const requestedKind = params.get('kind')
  const kind: WhatIfImpactKind =
    requestedKind === 'ALL' || requestedKind === 'REQUIRED' || requestedKind === 'PREFERRED'
      ? requestedKind
      : selected === undefined
        ? 'ALL'
        : defaultWhatIfImpactKind(selected)

  const whatIf = useWhatIf(
    target.data?.targetKey,
    selected?.affectedJobCount === null ? undefined : selected?.techId,
    { page, perPage: PER_PAGE, kind },
  )
  const data = whatIf.data
  const jobs = data === undefined ? [] : toWhatIfJobs(data)
  const impact = data?.impactCounts ?? null
  const ready = hasComputedValue(data)

  return (
    <div>
      <Link
        to="/recommendations"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 학습 추천
      </Link>

      <div className="mt-3">
        <PageHero
          title={
            selected === undefined
              ? '추천 기술 관련 공고'
              : `${selected.techName} 관련 공고`
          }
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
                onClick={() => setParams({
                  tech: candidate.techId,
                  kind: defaultWhatIfImpactKind(candidate),
                  page: '1',
                })}
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
                {(candidate.requiredImpactCount ?? 0) > 0 ? (
                  <span className="text-[12.5px] font-extrabold text-brand-600">
                    필수 {candidate.requiredImpactCount?.toLocaleString('ko-KR')}건
                  </span>
                ) : (candidate.preferredImpactCount ?? 0) > 0 ? (
                  <span className="text-[12.5px] font-extrabold text-brand-600">
                    우대 {candidate.preferredImpactCount?.toLocaleString('ko-KR')}건
                  </span>
                ) : null}
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
            title="추천 기술이 없어요"
            description="학습 추천에서 후보를 확인한 뒤 관련 공고를 볼 수 있습니다."
            action={
              <Link
                to="/recommendations"
                className="gj-clickable inline-flex rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink"
              >
                학습 추천 확인
              </Link>
            }
          />
        )}

        {ready && selected !== undefined && (
          /*
           * v2의 `571 / 757`. 왼쪽이 가정, 오른쪽이 그 결과로 새로 매칭되는 공고다.
           *
           * `items-start` 가 있어야 왼쪽 카드가 제 내용만큼만 선다 · 티켓 S15P21E102-377.
           * grid 의 기본 정렬은 stretch 라, 공고가 수십 건이면 왼쪽 카드가 그 높이까지
           * 늘어나 아래가 통째로 빈 흰 면이 됐다. 두 칸의 높이는 서로 다른 것을 세는
           * 값이라 맞출 이유가 없다 — 왼쪽은 기술 하나, 오른쪽은 공고 목록이다.
           */
          <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[571px_minmax(0,1fr)]">
            <DataRegion title="추천 기술">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[22px] leading-[1.2] font-[750] tracking-[-0.03em] text-brand-ink">
                  {selected.techName}
                </h2>
                {selected.fromLevel !== null ? (
                  <LevelBadge level={selected.fromLevel} />
                ) : selected.evidenceStatus !== null && EVIDENCE_LABEL[selected.evidenceStatus] !== undefined ? (
                  <span className="rounded-lg border border-brand-line bg-white px-2 py-1 text-[11.5px] font-[750] text-brand-faint">
                    {EVIDENCE_LABEL[selected.evidenceStatus]}
                  </span>
                ) : null}
              </div>

              {impact === null ? (
                <p className="mt-5 text-[12.5px] leading-[1.7] text-brand-muted">
                  새 추천 기준의 공고 수를 계산하고 있습니다.
                </p>
              ) : (
                <div className="mt-5">
                  <ConditionImpactSummary
                    requiredCount={impact.requiredCount}
                    preferredCount={impact.preferredCount}
                    emphasis
                  />
                </div>
              )}

              <ReasonsDisclosure reasons={selected.reasons} />
            </DataRegion>

            <DataRegion title="공고 목록">
              {impact !== null && (
                <div className="mb-4 flex flex-wrap gap-2">
                  {([
                    ['ALL', `전체 ${formatImpactIncrease(impact.affectedCount)}`],
                    ['REQUIRED', `필수 ${formatImpactIncrease(impact.requiredCount)}`],
                    ['PREFERRED', `우대 ${formatImpactIncrease(impact.preferredCount)}`],
                  ] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={kind === value}
                      onClick={() => setParams({ tech: selected.techId, kind: value, page: '1' })}
                      className={`rounded-lg px-3 py-2 text-[12px] font-bold ${kind === value ? 'bg-tone-accent-bg text-brand-ink' : 'text-brand-muted hover:bg-[#F5F7FA]'}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {jobs.length === 0 ? (
                <StateCard
                  kind="EMPTY"
                  title={page > 1 && (data?.totalCount ?? 0) > 0
                    ? '이 페이지에는 남은 공고가 없어요'
                    : '관련 공고가 없어요'}
                  description={page > 1 && (data?.totalCount ?? 0) > 0
                    ? '활성 공고가 바뀌었을 수 있습니다. 이전 페이지로 돌아가 확인해 주세요.'
                    : '현재 활성 공고에 이 기술 언급이 없습니다.'}
                  action={
                    page > 1 ? (
                      <button type="button"
                        onClick={() => setParams({ tech: selected.techId, kind, page: String(page - 1) })}
                        className="gj-clickable inline-flex rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink"
                      >
                        이전 페이지
                      </button>
                    ) : (
                      <Link to="/jobs"
                        className="gj-clickable inline-flex rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink"
                      >
                        현재 공고 보기
                      </Link>
                    )
                  }
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
                          <div className="flex gap-1.5">
                            {job.requiredImpact && <span className="rounded bg-tone-accent-bg px-2 py-0.5 text-[11px] font-bold text-brand-ink">필수</span>}
                            {job.preferredImpact && <span className="rounded bg-tone-neutral-bg px-2 py-0.5 text-[11px] font-bold text-tone-neutral">우대</span>}
                            {job.conditional && <span className="rounded bg-tone-caution-bg px-2 py-0.5 text-[11px] font-bold text-tone-caution">조건 확인 필요</span>}
                          </div>
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
                  {/* 선택한 영향 종류의 전체 수와 현재 페이지 범위를 함께 보여준다. */}
                  <p className="mt-3 text-center text-[12px] text-brand-faint">
                    {`${data?.totalCount ?? jobs.length}건 중 ${(page - 1) * PER_PAGE + 1}~${(page - 1) * PER_PAGE + jobs.length}건 표시`}
                  </p>
                  <div className="mt-3 flex justify-center gap-2">
                    {page > 1 && <button type="button" onClick={() => setParams({ tech: selected.techId, kind, page: String(page - 1) })} className="rounded-lg border border-brand-line px-3 py-2 text-[12px] font-bold">이전</button>}
                    {data?.hasNext && <button type="button" onClick={() => setParams({ tech: selected.techId, kind, page: String(page + 1) })} className="rounded-lg border border-brand-line px-3 py-2 text-[12px] font-bold">다음</button>}
                  </div>
                </>
              )}
            </DataRegion>
          </div>
        )}
      </div>

    </div>
  )
}
