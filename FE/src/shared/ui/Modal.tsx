import { useEffect } from 'react'
import type { ReactNode } from 'react'

/**
 * 중앙 모달 · 티켓 S15P21E102-204.
 *
 * `CandidateDrawer`(우측 드로어)와 역할이 다르다. 드로어는 목록을 옆에 둔 채 한 건을
 * **판단**하는 자리라 화면을 가리지 않는 것이 중요했다. 이 모달은 지표 하나가 센
 * 것이 정확히 무엇인지 **확인**만 하고 돌아가는 자리라, 잠깐 덮고 닫는 편이 맞다.
 *
 * 닫는 길을 세 개 둔다 -- Escape · 바깥 클릭 · 닫기 버튼. 확인만 하러 들어온
 * 사용자를 한 경로로만 내보내지 않는다.
 */
export function Modal({
  title,
  description,
  onClose,
  children,
}: {
  title: string
  /** 이 목록이 무엇을 센 것인지. 지표 카드의 caption과 같은 기준을 적는다 */
  description?: string
  onClose: () => void
  children: ReactNode
}) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  // 모달이 떠 있는 동안 뒤 페이지가 같이 스크롤되면 어느 쪽을 움직이는지 알 수 없다.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="닫기"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-[rgba(16,26,46,0.32)]"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_24px_60px_rgba(25,47,81,0.24)]"
      >
        <header className="flex items-start justify-between gap-4 border-b border-brand-line px-[22px] py-5">
          <div className="min-w-0">
            <h2 className="text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              {title}
            </h2>
            {description !== undefined && (
              <p className="mt-1.5 text-[12.5px] leading-[1.5] text-brand-faint">{description}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg border border-brand-line px-3 py-1.5 text-[12.5px] font-bold text-brand-muted hover:border-brand-line-active"
          >
            닫기
          </button>
        </header>

        <div className="overflow-y-auto px-[22px] py-4">{children}</div>
      </div>
    </div>
  )
}
