import { useState } from 'react'
import { Link } from 'react-router'
import { toJobPosting } from '@/features/matching/api/adapter'
import { DataGapNotice } from '@/features/matching/components/DataGapNotice'
import { JobPostingCard } from '@/features/matching/components/JobPostingCard'
import { JobRequirementDrawer } from '@/features/matching/components/JobRequirementDrawer'
import { useJobMatches, useTarget } from '@/features/matching/hooks/useMatching'
import { formatCollectedAt } from '@/features/matching/model/presentation'
import { targetRoleDisplayName } from '@/features/matching/model/targetOptions'
import type { JobPostingView } from '@/features/matching/model/view'
import { hasComputedValue } from '@/shared/api/computeState'
import { ComputeStatePanel, PartialNotice } from '@/shared/ui/ComputeStatePanel'
import { DataRegion } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
import type { StatItem } from '@/shared/ui/StatStrip'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 공고 매칭 · 확정 디자인 `Final v2`의 `02 Job Match` (S15P21E102-279).
 *
 * <h2>화면이 세지 않는다</h2>
 *
 * 충족 건수도 비교 대상 공고 수도 서버가 준 값을 그대로 쓴다. 목록에서 세면 페이지에
 * 담긴 만큼만 세게 되고, 그 숫자는 화면 상단의 "87건"과 어긋난다.
 *
 * <h2>필터는 목표 직무에 붙어 있다</h2>
 *
 * 지역·경력을 화면에서 잘라내지 않는다. 그렇게 하면 비율의 분모와 목록의 분모가
 * 달라진다. 조건을 바꾸려면 목표 직무를 바꿔야 하고, 그러면 서버가 같은 조건의
 * 공고 집합을 다시 고른다.
 *
 * **기술요건 충족만 보여준다.** 합격 가능성이나 지원 가능 여부를 판정하지 않는다.
 */

/** 한 쪽에 담을 공고 수. C의 상한이 50이라 그보다 작게 둔다. */
const PER_PAGE = 20

function toStats(
  summary: { totalCount: number; fullMatchCount: number | null } | null,
  scopeText: string,
): readonly StatItem[] {
  return [
    {
      label: '대조한 공고',
      note: summary === null ? '대조 후 표시' : `${summary.totalCount}건`,
      caption: scopeText,
    },
    {
      label: '필수 100% 충족',
      note:
        summary === null || summary.fullMatchCount === null
          ? '대조 후 표시'
          : `${summary.fullMatchCount}건`,
      caption: '모든 필수 기술 보유',
    },
    {
      /*
        세 번째 칸이 "75~99%"가 아닌 이유. C가 충족도 분포를 주지 않아 그 구간을
        셀 수 없고, 목록을 모아 세면 그것이 부합 판정 재계산이다(계약 §6-1).
        빈 칸을 남기는 대신 셀 수 있는 것을 보여준다.
      */
      label: '조건부 제외',
      note: summary === null ? '대조 후 표시' : '목록에서 제외',
      caption: '자격 조건이 확정되지 않아 대조하지 않은 공고',
    },
  ]
}

/**
 * 충족률 높은 순으로 늘어놓는다 · 티켓 S15P21E102-291.
 *
 * **비율을 화면이 만들지 않는다.** `fulfillmentRatio` 는 C가 계산해 준 값이고
 * (`JobMatchItemDto`), 여기서는 그 값으로 순서만 정한다. 칩을 세어 비율을 구하면
 * 미판정 절을 어떻게 세느냐에 따라 답이 달라지고, 그건 부합 판정을 화면에서 다시
 * 하는 일이다.
 *
 * C가 비율을 주지 않은 공고(`null`)는 **맨 뒤로 보내되 서로의 순서는 건드리지 않는다**.
 * 판정하지 못한 것을 0으로 취급해 "가장 안 맞는 공고"로 보이게 하면 안 된다.
 *
 * **이 정렬은 받아 온 페이지 안에서만 유효하다.** `GET /me/job-matches` 에 정렬
 * 파라미터가 없어 서버가 어떤 순서로 주는지 알 수 없고, 페이지를 넘기면 다음 묶음이
 * 다시 자기들끼리 정렬된다. 전체에서 충족률이 가장 높은 공고를 앞에 세우려면 서버가
 * 정렬해 줘야 한다 — BE 에 요청할 항목이다.
 */
function sortByFulfillment(postings: readonly JobPostingView[]): JobPostingView[] {
  return [...postings].sort((a, b) => {
    if (a.fulfillmentRatio === null && b.fulfillmentRatio === null) {
      return 0
    }
    if (a.fulfillmentRatio === null) {
      return 1
    }
    if (b.fulfillmentRatio === null) {
      return -1
    }
    return b.fulfillmentRatio - a.fulfillmentRatio
  })
}

export function JobMatchPage() {
  const [page, setPage] = useState(1)
  const [openPosting, setOpenPosting] = useState<JobPostingView | null>(null)

  const target = useTarget()
  const matches = useJobMatches(target.data?.targetKey, {
    page,
    perPage: PER_PAGE,
    includeConditional: true,
  })

  const data = matches.data
  const postings = sortByFulfillment(data?.items.map(toJobPosting) ?? [])
  const basis = data?.basis
  // 공고 목록은 추천 계산 상태와 별개다. BE 는 `INSUFFICIENT_DATA`·`INSUFFICIENT_EVIDENCE`
  // 에서도 items 를 그대로 싣는데(`JobMatchResponse.of`), 추천 상태로 목록까지 막으면
  // 수집된 공고가 수십 건 있어도 화면에는 안내 문구만 남는다. 그래서 목록은 items 유무로
  // 연다. 통계는 그대로 계산 상태를 따른다 -- 표본이 부족한 채로 비율을 보여주면 그 숫자가
  // 실제보다 확정적으로 읽힌다.
  const hasJobItems = data !== undefined && Array.isArray(data.items) && data.items.length > 0
  const scopeText =
    basis === undefined
      ? '선택한 직무의 수집된 공고 전체'
      : [targetRoleDisplayName(basis.targetRole), ...basis.regions, ...basis.careerLevels]
          .filter(Boolean)
          .join(' · ')

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero title="내 기술과 맞는 공고" />
        {/* 비교 기준을 항상 함께 둔다. 기준을 숨기면 숫자가 절대값으로 읽힌다 */}
        <div className="shrink-0 rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
          <p className="text-[12px] text-brand-faint">공고 업데이트</p>
          <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
            {formatCollectedAt(basis?.asOf)}
          </p>
        </div>
      </div>

      <div className="mt-7 grid gap-4">
        <PartialNotice state={data} />

        <ComputeStatePanel
          isLoading={target.isLoading || matches.isLoading}
          error={target.error ?? matches.error}
          state={data}
          loadingLabel="공고 대조 결과를 불러오는 중입니다."
          onRetry={() => void matches.refetch()}
        />

        {(hasComputedValue(data) || hasJobItems) && data !== undefined && (
          <>
            {hasComputedValue(data) && (
              <>
                <StatStrip items={toStats(data.summary, scopeText)} />

                {data.summary !== null && data.summary.excludedConditionalCount > 0 && (
                  <p className="text-[12px] leading-[1.6] text-brand-faint">
                    자격 조건이 확정되지 않아 {data.summary.excludedConditionalCount}건을 목록에서
                    제외했습니다. 충족하지 못한 공고가 아니라 대조하지 않은 공고입니다.
                  </p>
                )}
              </>
            )}

            <div className="gj-split">
              <DataRegion title="공고 목록">
                {postings.length === 0 ? (
                  <StateCard
                    kind="EMPTY"
                    title="조건에 맞는 공고가 없어요"
                    description="이번 수집분에 이 조건의 공고가 없습니다. 목표 직무에서 지역이나 경력 범위를 넓혀보세요."
                    action={
                      <Link
                        to="/roles"
                        className="inline-block rounded-xl border border-brand-line px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
                      >
                        목표 직무 바꾸기
                      </Link>
                    }
                  />
                ) : (
                  <>
                    <div className="grid gap-2.5">
                      {postings.map((posting) => (
                        <JobPostingCard
                          key={posting.id}
                          posting={posting}
                          onOpen={() => setOpenPosting(posting)}
                        />
                      ))}
                    </div>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <button
                        type="button"
                        disabled={page <= 1}
                        onClick={() => setPage((current) => Math.max(1, current - 1))}
                        className="rounded-xl border border-brand-line px-4 py-2 text-[13px] font-[750] text-brand-ink disabled:cursor-not-allowed disabled:text-brand-faint"
                      >
                        이전
                      </button>
                      <p className="text-[12px] text-brand-faint">
                        {data.summary === null
                          ? `${page}쪽`
                          : `${data.summary.totalCount}건 중 ${page}쪽`}
                      </p>
                      <button
                        type="button"
                        disabled={!data.hasNext}
                        onClick={() => setPage((current) => current + 1)}
                        className="rounded-xl border border-brand-line px-4 py-2 text-[13px] font-[750] text-brand-ink disabled:cursor-not-allowed disabled:text-brand-faint"
                      >
                        다음
                      </button>
                    </div>
                  </>
                )}
              </DataRegion>

              <div className="grid gap-4">
                <DataRegion title="부족한 기술">
                  <DataGapNotice gaps={data.dataGaps} className="mt-4" />

                  <Link
                    to="/skill-gap"
                    className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
                  >
                    부족한 기술 자세히 보기
                  </Link>
                  <Link
                    to="/recommendations"
                    className="mt-2.5 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
                  >
                    다음 기술 추천 보기
                  </Link>
                </DataRegion>
              </div>
            </div>
          </>
        )}
      </div>

      <JobRequirementDrawer posting={openPosting} onClose={() => setOpenPosting(null)} />

    </div>
  )
}
