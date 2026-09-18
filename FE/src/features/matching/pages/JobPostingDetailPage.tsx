import { Link, useParams } from 'react-router'
import { toJobPosting } from '@/features/matching/api/adapter'
import { RequirementChip } from '@/features/matching/components/RequirementChip'
import { useJobMatch, useTarget } from '@/features/matching/hooks/useMatching'
import type { JobPostingView } from '@/features/matching/model/view'
import { hasComputedValue } from '@/shared/api/computeState'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { DataRegion } from '@/shared/ui/DataRegion'
import { SegmentBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 공고 상세 · 티켓 S15P21E102-291.
 *
 * 목록(화면 02)의 드로어가 요건 대조만 빠르게 보여 준다면, 이 화면은 **공고 한 건이
 * 가진 값을 전부** 펼친다. 수집기가 실제로 남기는 필드(`postings.csv`)가 회사·지역·
 * 경력·마감·출처·원문 링크까지 있고, 드로어의 폭으로는 그것을 다 두지 못한다.
 *
 * 주소로 바로 들어올 수 있어야 해서 별도 라우트(`/jobs/:jobId`)를 둔다. 공고 링크를
 * 팀에 공유하거나 새로고침해도 같은 화면이 떠야 한다.
 *
 * ## 이 화면이 지키는 구분
 *
 * **"해석하지 못한 요구"를 "충족하지 못한 요구"로 보여주지 않는다.** 판정하지 않은
 * 요구는 사용자 행동으로 이어지지 않으므로 화면에서 숨기고 확인된 기술만 표시한다.
 *
 * 값을 만들지 않는다. 충족률(`fulfillmentRatio`)도 C가 계산한 것을 받아 표시만 한다.
 */

/** 값이 없는 축은 뺀다. `서울 · · D-11` 같은 빈칸을 남기지 않는다. */
function metaItems(posting: JobPostingView): { label: string; value: string }[] {
  return [
    { label: '회사', value: posting.companyName },
    { label: '근무지', value: posting.region ?? '' },
    { label: '경력', value: posting.career ?? '' },
    { label: '마감', value: posting.deadlineText ?? '' },
    { label: '출처', value: posting.sourceSite ?? '' },
  ].filter((item) => item.value !== '')
}

function countHave(requirements: readonly { mark: string }[]): number {
  return requirements.filter((item) => item.mark === 'HAVE').length
}

function countUnknown(requirements: readonly { mark: string }[]): number {
  return requirements.filter((item) => item.mark === 'UNKNOWN').length
}

/**
 * 요건 묶음 하나(필수 / 우대).
 *
 * 분수를 크게 두고 칸 막대를 아래에 둔다. 퍼센트 하나로 합치지 않는 이유는 목록
 * 카드와 같다 — `4개 중 3개`와 `8개 중 6개`는 같은 75%라도 다른 상황이다.
 */
function RequirementBlock({
  title,
  requirements,
}: {
  title: string
  requirements: readonly JobPostingView['required'][number][]
}) {
  const have = countHave(requirements)
  const unknown = countUnknown(requirements)

  if (requirements.length === 0) {
    return (
      <section className="rounded-[14px] border border-brand-line bg-white p-[18px]">
        <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">{title}</p>
        <p className="mt-2 text-[13px] text-brand-muted">
          이 공고에서 해석된 {title} 요건이 없습니다.
        </p>
      </section>
    )
  }

  return (
    <section className="rounded-[14px] border border-brand-line bg-white p-[18px]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">{title}</p>
        <p className="text-[18px] leading-none font-[850] tracking-[-0.03em] text-brand-ink-soft tabular-nums">
          {have}
          <span className="text-[13px] font-bold text-brand-faint">
            {' / '}
            {requirements.length}
          </span>
        </p>
      </div>

      <div className="mt-3">
        <SegmentBar marks={requirements.map((item) => item.mark)} />
      </div>

      <div className="mt-3.5 flex flex-wrap gap-1.5">
        {requirements.map((requirement) => (
          <RequirementChip key={requirement.techName} requirement={requirement} />
        ))}
      </div>

      {/*
        미판정을 분수 밖에 적는다. 분모에만 넣고 말하지 않으면 "충족하지 못한 것"으로
        읽힌다.
      */}
      {unknown > 0 && (
        <p className="mt-3 text-[12px] text-tone-neutral">
          이 중 {unknown}건은 요구 수준을 해석하지 못해 충족 여부를 판정하지 않았습니다.
        </p>
      )}
    </section>
  )
}

export function JobPostingDetailPage() {
  const { jobId } = useParams()
  const target = useTarget()
  const detail = useJobMatch(target.data?.targetKey, jobId)
  const item = detail.data?.item ?? null
  const posting = item === null ? null : toJobPosting(item)
  const required = posting?.required.filter((requirement) => requirement.mark !== 'UNKNOWN') ?? []
  const preferred = posting?.preferred.filter((requirement) => requirement.mark !== 'UNKNOWN') ?? []

  return (
    <div>
      <Link
        to="/jobs"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 공고 매칭
      </Link>

      <div className="mt-3">
        <PageHero title={posting?.title ?? '공고 상세'} />
      </div>

      <div className="mt-6">
        <ComputeStatePanel
          isLoading={target.isLoading || detail.isLoading}
          error={target.error ?? detail.error}
          state={detail.data}
          onRetry={() => void detail.refetch()}
        />
      </div>

      {hasComputedValue(detail.data) && posting === null && (
        <div className="mt-4">
          <StateCard
            kind="EMPTY"
            title="공고를 찾을 수 없어요"
            description="주소가 바뀌었거나 공고가 목록에서 내려갔을 수 있습니다."
            action={
              <Link to="/jobs" className="text-tone-accent underline">
                공고 목록으로
              </Link>
            }
          />
        </div>
      )}

      {posting !== null && (
        <div className="gj-split mt-4">
          <div className="grid gap-3">
            <RequirementBlock title="필수" requirements={required} />
            <RequirementBlock title="우대" requirements={preferred} />
          </div>

          <div className="grid gap-4">
            <DataRegion title="공고 정보">
              <dl className="grid gap-2.5">
                {metaItems(posting).map((meta) => (
                  <div key={meta.label} className="flex items-baseline justify-between gap-3">
                    <dt className="shrink-0 text-[12px] text-brand-faint">{meta.label}</dt>
                    <dd className="min-w-0 text-right text-[13px] font-semibold text-brand-ink-soft">
                      {meta.value}
                    </dd>
                  </div>
                ))}
              </dl>

              {/*
                원문 링크가 유일한 확인 경로다. 우리는 공고 본문을 저장하지 않는다.
              */}
              {posting.sourceUrl !== null && (
                <a
                  href={posting.sourceUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="gj-clickable mt-4 block rounded-xl border border-brand-line bg-white px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink"
                >
                  원문 공고 보기 ↗
                </a>
              )}
            </DataRegion>

            <DataRegion title="부족한 기술">
              <Link
                to="/skill-gap"
                className="gj-clickable block rounded-xl border border-brand-line bg-white px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink"
              >
                부족한 기술 보기 →
              </Link>
            </DataRegion>
          </div>
        </div>
      )}

    </div>
  )
}
