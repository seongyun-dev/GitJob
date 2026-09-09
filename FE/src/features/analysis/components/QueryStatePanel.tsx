import { ApiError } from '@/shared/api/client'
import type { ErrorAction } from '@/shared/api/errorCodes'

/**
 * 조회 상태 표시 · 티켓 S15P21E102-117.
 *
 * 오류 문구는 두 층으로 나눈다. 서버가 준 `message`를 그대로 제목으로 쓰고,
 * 다음 행동은 `ApiError.action`으로 정한다. 컴포넌트에 코드 문자열 비교를
 * 흩어놓지 않는다는 규약(`shared/api/errorCodes`)을 화면에서도 지키는 방식이다.
 *
 * `shared/ui`에 두지 않은 이유: 공통 컴포넌트 구성은 프론트엔드 설계 5장이
 * 소유하는데 그 문서를 이 환경에서 볼 수 없다. 136·137·138이 같은 상태 UI를
 * 필요로 하므로, 그때 설계 5장을 확인해 `shared/ui`로 올린다.
 */

/**
 * 다음 행동 안내.
 *
 * 제목에는 서버가 준 `message`가 들어간다. 그 문장이 이미 "무엇이 잘못됐는지"를
 * 말하므로 여기서 원인을 다시 쓰지 않는다. QA에서 `REPO-409-1`과 매핑 없는 코드가
 * 제목과 거의 같은 문장을 두 번 보여줬고, 그래서 이 표는 행동만 담는다.
 *
 * 빈 문자열은 "덧붙일 행동이 없다"는 뜻이고 그 줄은 렌더하지 않는다.
 */
const GUIDANCE: Readonly<Record<ErrorAction, string>> = {
  REDIRECT_TO_ONBOARDING: 'GitHub을 다시 연결한 뒤 이용해 주세요.',
  RECONNECT_GITHUB: 'GitHub에서 저장소 접근 권한을 다시 허용해 주세요.',
  SHOW_FORBIDDEN: '다른 저장소를 선택하거나 GitHub에서 접근 권한을 확인해 주세요.',
  SHOW_NOT_FOUND: '목록을 다시 불러온 뒤 선택해 주세요.',
  SHOW_EMPTY_WITH_CTA: '',
  SILENT_EMPTY: '',
  SHOW_RATE_LIMIT: '',
  SHOW_RETRY: '일시적인 문제일 수 있습니다.',
  SHOW_INLINE_ERROR: '선택한 값을 확인해 주세요.',
  SHOW_UNANALYZABLE: '다른 저장소를 선택해 주세요.',
  SHOW_GENERIC_ERROR: '잠시 후 다시 시도하고, 계속되면 아래 코드와 함께 문의해 주세요.',
}

/** 목록 컨테이너·선택 패널과 같은 카드 모양을 쓴다. 옅은 회색 배경 위에서 카드가 떠 보여야 한다. */
/** Final 카드와 같은 표면: radius 18px · border 1px #E0E7F1 · shadow rgba(25,47,81,0.07) 0 10px 28px. */
const PANEL =
  'rounded-[18px] border border-brand-line bg-white px-5 py-6 text-sm shadow-[0_10px_28px_rgba(25,47,81,0.07)]'

export function LoadingPanel({ label }: { label: string }) {
  return (
    <div className={`${PANEL} text-brand-muted`} role="status" aria-live="polite">
      {label}
    </div>
  )
}

export function EmptyPanel({ title, description }: { title: string; description: string }) {
  return (
    <div className={PANEL}>
      <p className="text-[15px] font-semibold text-brand-ink">{title}</p>
      <p className="mt-1.5 leading-[1.6] text-brand-muted">{description}</p>
    </div>
  )
}

/**
 * 재시도 버튼은 `SHOW_RETRY`에서만 노출한다. 4xx는 같은 요청을 다시 보내도 답이 같고,
 * 429는 서버가 `Retry-After`로 시점을 지시하므로 버튼 대신 대기 시간을 안내한다.
 */
export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const isApi = error instanceof ApiError
  const action: ErrorAction = isApi ? error.action : 'SHOW_GENERIC_ERROR'
  const headline = isApi ? error.message : '요청을 처리할 수 없습니다.'
  const retryAfterSec = isApi ? error.retryAfterSec : null
  const guidance = GUIDANCE[action]

  return (
    <div className={`${PANEL} border-tone-danger-bg`} role="alert">
      <p className="font-medium text-tone-danger">{headline}</p>
      {guidance !== '' && <p className="mt-1 leading-[1.6] text-brand-muted">{guidance}</p>}
      {retryAfterSec !== null && (
        <p className="mt-1 text-tone-caution">약 {retryAfterSec}초 후에 다시 시도할 수 있습니다.</p>
      )}
      {action === 'SHOW_RETRY' && onRetry !== undefined && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-xl border border-brand-line px-3.5 py-2 text-[13px] font-semibold text-brand-ink hover:border-brand-line-active hover:bg-neutral-50"
        >
          다시 시도
        </button>
      )}
      {isApi && (
        // 팀 문의 시 코드가 있으면 원인 추적이 빠르다. 스택이나 내부 메시지는 노출하지 않는다.
        <p className="mt-3 font-evidence text-xs text-brand-faint">코드 {error.code}</p>
      )}
    </div>
  )
}
