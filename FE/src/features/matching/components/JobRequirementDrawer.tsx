import type { JobPostingView, JobRequirement } from '@/features/matching/model/view'
import { MeterBar } from '@/shared/ui/MeterBar'

/**
 * 공고 기술요건 상세 드로어 · 화면 02 Job Match.
 *
 * 확정 디자인 `Final v2`는 공고를 누르면 오른쪽에서 436px 패널이 밀려 나온다.
 * 목록에서는 칩으로 요약하고, 여기서는 기술 하나하나에 판정 문구를 붙인다.
 *
 * 드로어를 화면 컴포넌트 안에 인라인으로 두지 않은 이유는 열림 상태와 무관하게
 * 항상 DOM에 있어야 `transform` 전환이 되기 때문이다. 열릴 때 마운트하면 미끄러지지
 * 않고 튀어나온다.
 *
 * 닫혀 있을 때는 `inert`로 초점이 들어가지 않게 한다. 화면 밖 패널의 링크에 Tab이
 * 걸리면 키보드 사용자가 보이지 않는 곳을 헤맨다.
 */
const VERDICT: Readonly<Record<JobRequirement['mark'], { text: string; className: string }>> = {
  HAVE: { text: '보유', className: 'text-tone-success' },
  WEAK: { text: '강화 필요', className: 'text-tone-caution' },
  NONE: { text: '근거 없음', className: 'text-brand-faint' },
  // 근거가 없는 것이 아니라 판정하지 않은 것이다. 같은 문구를 쓰면 구분이 사라진다.
  UNKNOWN: { text: '판정 못 함', className: 'text-tone-neutral' },
}

function RequirementList({
  title,
  requirements,
}: {
  title: string
  requirements: readonly JobRequirement[]
}) {
  if (requirements.length === 0) {
    return null
  }

  return (
    <div>
      <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">{title}</p>
      <ul className="mt-2 grid gap-1.5">
        {requirements.map((requirement) => {
          const verdict = VERDICT[requirement.mark]
          return (
            <li
              key={requirement.techName}
              className="flex items-center justify-between gap-3 rounded-[10px] border border-brand-line bg-white/70 px-3.5 py-2.5"
            >
              <span className="truncate text-[13px] font-semibold text-brand-ink-soft">
                {requirement.techName}
              </span>
              <span className={`shrink-0 text-[12.5px] font-[750] ${verdict.className}`}>
                {verdict.text}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function JobRequirementDrawer({
  posting,
  onClose,
}: {
  /** 열 공고. 닫혀 있으면 `null`이고 패널은 화면 밖에 남는다. */
  posting: JobPostingView | null
  onClose: () => void
}) {
  const open = posting !== null
  const requiredHave = posting?.required.filter((item) => item.mark === 'HAVE').length ?? 0
  const preferredHave = posting?.preferred.filter((item) => item.mark === 'HAVE').length ?? 0

  return (
    <>
      {/* 스크림. 닫혀 있을 때 클릭을 통과시켜 아래 목록을 막지 않는다 */}
      <div
        aria-hidden
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-[rgba(16,26,46,0.14)] transition-opacity duration-200 ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
      />

      <aside
        aria-label="공고 기술요건 상세"
        aria-hidden={!open}
        inert={!open}
        className={`fixed top-0 right-0 bottom-0 z-50 flex w-full max-w-[436px] flex-col border-l border-brand-line bg-white shadow-[-24px_0_64px_rgba(19,39,77,0.16)] transition-transform duration-300 ${
          open ? 'translate-x-0' : 'translate-x-[104%]'
        }`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-brand-line px-6 py-5">
          <div className="min-w-0">
            <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
              JOB REQUIREMENT DETAIL
            </p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              {posting?.title ?? ''}
            </h2>
            <p className="mt-1 text-[12px] text-brand-faint">
              {posting === null
                ? ''
                : [posting.companyName, posting.region, posting.career, posting.deadline]
                    .filter((value) => value !== null && value !== '')
                    .join(' · ')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="shrink-0 rounded-lg border border-brand-line px-2.5 py-1.5 text-[13px] text-brand-muted hover:text-brand-ink"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {posting !== null && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-[11.5px] text-brand-faint">필수 충족</p>
                  <p className="mt-1 text-[20px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
                    {requiredHave}
                    <span className="text-[13px] font-bold text-brand-faint">
                      {' / '}
                      {posting.required.length}
                    </span>
                  </p>
                  <div className="mt-2">
                    <MeterBar
                      value={requiredHave}
                      total={posting.required.length}
                      height={6}
                    />
                  </div>
                </div>
                <div>
                  <p className="text-[11.5px] text-brand-faint">우대 충족</p>
                  <p className="mt-1 text-[20px] leading-none font-[850] tracking-[-0.04em] text-brand-ink-soft">
                    {preferredHave}
                    <span className="text-[13px] font-bold text-brand-faint">
                      {' / '}
                      {posting.preferred.length}
                    </span>
                  </p>
                  <div className="mt-2">
                    <MeterBar
                      value={preferredHave}
                      total={posting.preferred.length}
                      tone="muted"
                      height={6}
                    />
                  </div>
                </div>
              </div>

              <div className="mt-6 grid gap-5">
                <RequirementList title="필수 기술" requirements={posting.required} />
                <RequirementList title="우대 기술" requirements={posting.preferred} />

                {/*
                  해석하지 못한 요구. 부족으로 세지 않고 따로 적는다 -- 공고가 무엇을
                  요구했는지 우리가 읽지 못한 것이지, 사용자가 못 갖춘 것이 아니다.
                */}
                {posting.unresolved.length > 0 && (
                  <div>
                    <p className="text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
                      해석하지 못한 요구
                    </p>
                    <ul className="mt-2 grid gap-1.5">
                      {posting.unresolved.map((item) => (
                        <li
                          key={`${item.requirementKind}-${item.reason}`}
                          className="rounded-[10px] border border-brand-line bg-[#F7F9FC] px-3.5 py-2.5 text-[12.5px] leading-[1.6] text-brand-muted"
                        >
                          {item.requirementKind === 'REQUIRED' ? '필수' : '우대'} · {item.reason}
                          {item.knownTechIds.length > 0 && ` (${item.knownTechIds.join(', ')})`}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="border-t border-brand-line px-6 py-4">
          {posting?.sourceUrl != null && (
            <a
              href={posting.sourceUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="mb-3 block rounded-xl border border-brand-line px-4 py-2.5 text-center text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              원문 공고 보기{posting.sourceSite === null ? '' : ` · ${posting.sourceSite}`}
            </a>
          )}
          <p className="text-[11.5px] leading-[1.6] text-brand-faint">
            보유 여부는 GitHub Personal Evidence 기준입니다. 기술요건 충족 여부만 보여주며 지원
            결과를 예측하지 않습니다.
          </p>
        </div>
      </aside>
    </>
  )
}
