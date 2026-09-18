import { RequirementChip } from '@/features/matching/components/RequirementChip'
import type { JobPostingView } from '@/features/matching/model/view'
import { SegmentBar } from '@/shared/ui/MeterBar'

/**
 * 공고 카드 · 화면 02 Job Match.
 *
 * 확정 디자인 `Final v2`의 공고 행은 왼쪽에 공고 정보와 기술 칩, 오른쪽에 충족
 * 요약을 둔다. 오른쪽 요약이 `3 / 4` 같은 **분수**인 것이 중요하다. 퍼센트만 쓰면
 * "4개 중 3개"와 "8개 중 6개"가 같은 75%로 보이는데, 하나만 더 채우면 되는 공고와
 * 둘을 채워야 하는 공고는 다른 상황이다.
 *
 * 그래서 막대도 비율 하나가 아니라 요구 절 수만큼 칸을 나눈다(`SegmentBar`).
 *
 * **"필수 전체 충족" 배지는 서버의 `requiredStatus`로만 붙인다(S15P21E102-279).**
 * 칩을 세어 판단하지 않는다 — 그건 부합 판정을 화면에서 다시 하는 것이고, 미판정
 * 절이 섞여 있으면 세는 방식에 따라 답이 달라진다.
 */
function countHave(requirements: readonly { mark: string }[]): number {
  return requirements.filter((item) => item.mark === 'HAVE').length
}

/** 값이 없는 축은 뺀다. `서울 · · D-11` 같은 빈칸을 남기지 않는다. */
function metaText(posting: JobPostingView): string {
  return [posting.companyName, posting.region, posting.career, posting.deadlineText]
    .filter((value) => value !== null && value !== '')
    .join(' · ')
}

export function JobPostingCard({
  posting,
  onOpen,
}: {
  posting: JobPostingView
  /** 상세 드로어 열기. */
  onOpen: () => void
}) {
  const requiredHave = countHave(posting.required)
  const preferredHave = countHave(posting.preferred)
  const fullMatch = posting.requiredStatus === 'FULL'
  const unknownCount = posting.required.filter((item) => item.mark === 'UNKNOWN').length

  return (
    <button
      type="button"
      onClick={onOpen}
      className="grid w-full grid-cols-1 items-start gap-4 rounded-[16px] border border-brand-line bg-white px-5 py-4 text-left transition-colors hover:border-brand-line-active lg:grid-cols-[minmax(0,1fr)_180px]"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[14.5px] font-[750] tracking-[-0.02em] text-brand-ink">
            {posting.title}
          </p>
          {fullMatch && (
            <span className="rounded-full bg-tone-success-bg px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.08em] text-tone-success">
              필수 전체 충족
            </span>
          )}
        </div>
        <p className="mt-1 text-[12px] text-brand-faint">{metaText(posting)}</p>

        <div className="mt-3 grid gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10.5px] font-extrabold tracking-[0.1em] text-brand-faint">
              필수
            </span>
            {posting.required.length === 0 ? (
              <span className="text-[12px] text-brand-faint">해석된 필수 요건 없음</span>
            ) : (
              posting.required.map((requirement) => (
                <RequirementChip key={requirement.techName} requirement={requirement} />
              ))
            )}
          </div>
          {posting.preferred.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10.5px] font-extrabold tracking-[0.1em] text-brand-faint">
                우대
              </span>
              {posting.preferred.map((requirement) => (
                <RequirementChip key={requirement.techName} requirement={requirement} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 충족 요약. 분수를 크게 두고 칸 막대를 그 아래에 둔다 */}
      <div className="lg:pl-4 lg:border-l lg:border-brand-line">
        <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">필수 충족</p>
        <p
          className={`mt-1 text-[24px] leading-none font-[850] tracking-[-0.04em] ${
            fullMatch ? 'text-tone-success' : 'text-brand-ink-soft'
          }`}
        >
          {requiredHave}
          <span className="text-[14px] font-bold text-brand-faint">
            {' / '}
            {posting.required.length}
          </span>
        </p>
        <div className="mt-2.5">
          <SegmentBar marks={posting.required.map((item) => item.mark)} />
        </div>
        <p className="mt-2 text-[11.5px] text-brand-faint">
          우대 {preferredHave} / {posting.preferred.length}
        </p>
        {/*
          판정하지 못한 요건이 몇 개인지 밝힌다. 밝히지 않으면 분수의 분모만 커져
          "충족하지 못한 것"으로 읽힌다.
        */}
        {unknownCount > 0 && (
          <p className="mt-1 text-[11.5px] text-tone-neutral">미판정 {unknownCount}건 포함</p>
        )}
      </div>
    </button>
  )
}
