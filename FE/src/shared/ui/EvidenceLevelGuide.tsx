import { LEVEL_MEANING } from '@/shared/constants/evidenceLevel'
import { EVIDENCE_LEVELS } from '@/shared/types/domain'

/**
 * Evidence Level 도움말.
 *
 * 숫자가 숙련도 점수처럼 읽히지 않도록, 저장소에서 확인한 코드 근거의 범위라는 점을
 * 먼저 설명한다. hover뿐 아니라 키보드 focus에서도 열려야 모바일·키보드 사용자가
 * 같은 내용을 확인할 수 있다.
 */
export function EvidenceLevelGuide() {
  return (
    <div className="group relative z-20 w-fit">
      <button
        type="button"
        aria-describedby="evidence-level-guide"
        className="inline-flex items-center gap-1.5 rounded-full border border-brand-line bg-white px-3 py-1.5 text-[12px] font-semibold text-brand-muted hover:border-brand-line-active hover:text-brand-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
      >
        L0~L3 기준
        <span
          aria-hidden
          className="inline-flex size-4 items-center justify-center rounded-full bg-tone-accent-bg text-[10px] font-extrabold text-brand-600"
        >
          ?
        </span>
      </button>

      <div
        id="evidence-level-guide"
        role="tooltip"
        className="invisible absolute top-full right-0 mt-2 w-[min(340px,calc(100vw-2rem))] rounded-[14px] border border-brand-line bg-white p-4 opacity-0 shadow-[0_16px_38px_rgba(25,47,81,0.16)] transition group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      >
        <p className="text-[12.5px] leading-[1.6] font-semibold text-brand-ink">
          숙련도 점수가 아니라 코드에서 확인한 사용 근거 단계입니다.
        </p>
        <dl className="mt-3 grid gap-2">
          {EVIDENCE_LEVELS.map((level) => (
            <div key={level} className="grid grid-cols-[28px_minmax(0,1fr)] gap-2">
              <dt className="font-evidence text-[11.5px] font-extrabold text-brand-600">
                {level}
              </dt>
              <dd className="text-[11.5px] leading-[1.55] text-brand-muted">
                {LEVEL_MEANING[level]}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
