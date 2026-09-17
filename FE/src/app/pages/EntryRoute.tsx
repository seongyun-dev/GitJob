import { Navigate } from 'react-router'
import { browserLandingSeenStorage, landingEntryPath } from '@/features/landing/model/landingEntry'

/**
 * `/` · 티켓 S15P21E102-310.
 *
 * 화면이 아니라 갈림길이다. 소개를 본 적 없으면 `/intro`, 봤으면 `/main` 으로 보낸다.
 * 판정 자체는 {@link landingEntryPath} 가 갖고 여기서는 읽어서 옮기기만 한다 — 그래야
 * 규칙을 DOM 없이 테스트할 수 있다.
 *
 * `replace` 인 이유는 뒤로 가기에서 이 갈림길로 돌아오지 않게 하기 위해서다. 히스토리에
 * 남겨 두면 `/intro` 에서 뒤로 갔을 때 `/` 가 다시 같은 곳으로 보내 되돌아갈 수 없다.
 *
 * 렌더 중에 결정해도 되는 이유는 이 판정이 localStorage 한 번 읽기이기 때문이다. 기다릴
 * 것이 없으므로 중간 화면을 두지 않는다 — 한 프레임짜리 빈 화면이 깜빡이는 편이 나쁘다.
 */
export function EntryRoute() {
  return <Navigate to={landingEntryPath(browserLandingSeenStorage())} replace />
}
