import { RequirementChip } from '@/features/matching/components/RequirementChip'
import type { JobPostingView } from '@/features/matching/model/view'
import { SegmentBar } from '@/shared/ui/MeterBar'

/**
 * 공고 카드 · 화면 02 Job Match.
 *
 * 왼쪽에는 공고 정보와 기술 칩, 오른쪽에는 확인된 기술 수를 둔다. 사용자가 직접
 * 해결할 수 없는 판정 보류 사유는 숨기고, 상세를 열 수 있다는 CTA를 항상 보여 준다.
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
  const required = posting.required.filter((item) => item.mark !== 'UNKNOWN')
  const preferred = posting.preferred.filter((item) => item.mark !== 'UNKNOWN')

  return (
    <button
      type="button"
      onClick={onOpen}
      className="gj-clickable-card group grid w-full cursor-pointer grid-cols-1 items-start gap-4 rounded-[16px] border border-[#C8D8FF] bg-white px-5 py-4 text-left lg:grid-cols-[minmax(0,1fr)_180px]"
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
            {required.length === 0 ? (
              <span className="text-[12px] text-brand-faint">해석된 필수 요건 없음</span>
            ) : (
              required.map((requirement) => (
                <RequirementChip key={requirement.techName} requirement={requirement} />
              ))
            )}
          </div>
          {preferred.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10.5px] font-extrabold tracking-[0.1em] text-brand-faint">
                우대
              </span>
              {preferred.map((requirement) => (
                <RequirementChip key={requirement.techName} requirement={requirement} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 확인된 기술만 요약한다. 판정 보류 절은 사용자 카드에 노출하지 않는다. */}
      <div className="lg:pl-4 lg:border-l lg:border-brand-line">
        <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
          확인된 필수 기술
        </p>
        <p
          className={`mt-1 text-[24px] leading-none font-[850] tracking-[-0.04em] ${
            fullMatch ? 'text-tone-success' : 'text-brand-ink-soft'
          }`}
        >
          {requiredHave}
          <span className="text-[14px] font-bold text-brand-faint">개 보유</span>
        </p>
        <div className="mt-2.5">
          <SegmentBar marks={required.map((item) => item.mark)} />
        </div>
        <p className="mt-2 text-[11.5px] text-brand-faint">
          우대 기술 {preferredHave}개 보유
        </p>
        <p className="mt-2 text-[12px] font-[750] text-brand-600 transition-colors group-hover:text-brand-ink">
          요건 자세히 보기 →
        </p>
      </div>
    </button>
  )
}
