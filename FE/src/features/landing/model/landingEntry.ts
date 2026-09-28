/**
 * 랜딩 진입 정책 · 티켓 S15P21E102-310.
 *
 * <h2>무엇을 정하나</h2>
 *
 * `/` 로 들어온 사람을 소개(`/intro`)로 보낼지 메인(`/main`)으로 보낼지, 그리고 그
 * 판정의 근거가 되는 "이미 봤다" 표식을 어떻게 읽고 쓰는지를 정한다.
 *
 * 소개는 한 번 보면 충분하다. 매번 다섯 장을 지나야 메인에 닿으면 이미 아는 사람에게는
 * 서비스가 느려지기만 한다. 그래서 자동 노출은 최초 1회로 두고, 다시 보고 싶은 사람은
 * 헤더의 "서비스 소개"로 언제든 `/intro` 에 들어온다. 그 경로는 이 판정을 거치지
 * 않는다 — 명시적으로 들어온 사람에게서 화면을 뺏는 동작이기 때문이다.
 *
 * <h2>왜 두 경로 상수가 여기 있나</h2>
 *
 * 둘은 이 판정의 두 결과다. 같은 파일에 두면 "어디로 갈 수 있는가"와 "무엇을 보고
 * 정하는가"가 함께 읽힌다. `MAIN_PATH` 는 `storyScenes` 에 있던 것을 옮겨 왔다.
 *
 * 실용적인 이유도 있다. 이 모듈은 **아무것도 import 하지 않는다**. `@/` 별칭은 Vite 가
 * 푸는 것이라 별칭을 쓰면 `node --test` 에서 해석되지 않고, 상대 경로는 확장자를
 * 요구한다. 의존이 없으면 둘 다 문제가 되지 않는다 — DOM 없이 돌릴 수 있게 순수
 * 모듈로 둔 이유를 import 하나로 잃지 않는다.
 *
 * <h2>왜 localStorage 인가</h2>
 *
 * sessionStorage 는 탭을 닫으면 사라져 "이미 봤다"를 담을 수 없고, 서버가 알아야 할
 * 값이 아니므로 Cookie 도 아니다. 인증·개인정보를 담지 않는 UX 표식이라 로그아웃과도
 * 무관하게 남는다 — 로그아웃했다고 소개를 다시 봐야 할 이유가 없다.
 *
 * Storage 를 인자로 받는 것은 `sessionSync` 와 같은 규칙이다. 모듈이 `window` 를 직접
 * 잡으면 테스트에서 실행할 수 없고, 실패 경로(막힌 Storage)를 재현할 방법도 사라진다.
 */

/**
 * 랜딩 스토리가 사는 곳.
 *
 * `/` 에서 옮겨 왔다. `/` 는 이제 화면이 아니라 갈림길이고, 랜딩에 고정된 주소가 있어야
 * "봤으면 건너뛴다"와 "언제든 다시 본다"가 한 화면에서 부딪히지 않는다.
 */
export const INTRO_PATH = '/intro'

/**
 * 랜딩의 시작 버튼이 가는 곳 · 메인 화면.
 *
 * GitHub OAuth 로 바로 나가지 않는다. 그러면 버튼을 누른 순간 우리 화면을 떠나 GitHub
 * 권한 동의 화면이 뜬다 — 무엇을 얻는지 아직 보지 못한 사람에게 권한부터 요구하는
 * 순서가 된다. 메인 화면에서 직무별 판정 범위를 본 뒤에 로그인이 필요해진다.
 */
export const MAIN_PATH = '/main'

/** 값은 표식 하나뿐이다. 개인정보도 인증정보도 담지 않는다. */
export const LANDING_SEEN_STORAGE_KEY = 'gitjob.landing.seen.v1'

const SEEN_VALUE = 'true'

export interface LandingSeenStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

/**
 * 브라우저의 localStorage. 쓸 수 없으면 `null`.
 *
 * 접근만으로 던지는 환경이 실제로 있다(일부 브라우저의 시크릿 모드, 사이트 데이터 차단).
 * 그래서 존재 확인까지 try 안에 둔다.
 */
export function browserLandingSeenStorage(): LandingSeenStorage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/**
 * 랜딩을 본 적이 있는지.
 *
 * 읽기가 실패하거나 값이 우리가 쓴 것과 다르면 **보지 않은 것으로** 읽는다. 소개를 한 번
 * 더 보는 것은 손해가 아니지만, 첫 화면이 비거나 예외로 죽는 것은 손해다.
 */
export function readLandingSeen(storage: LandingSeenStorage | null | undefined): boolean {
  if (storage === null || storage === undefined) {
    return false
  }
  try {
    return storage.getItem(LANDING_SEEN_STORAGE_KEY) === SEEN_VALUE
  } catch {
    return false
  }
}

/**
 * 랜딩을 봤다고 남긴다.
 *
 * 저장에 실패해도 삼킨다. 부르는 쪽이 CTA 클릭 핸들러다 — 표식을 남기지 못하면 다음
 * 방문에서 소개를 한 번 더 볼 뿐이고, 그 대가로 화면 이동을 막을 이유는 없다.
 */
export function markLandingSeen(storage: LandingSeenStorage | null | undefined): void {
  if (storage === null || storage === undefined) {
    return
  }
  try {
    storage.setItem(LANDING_SEEN_STORAGE_KEY, SEEN_VALUE)
  } catch {
    /* 저장하지 못해도 이동은 계속한다. */
  }
}

/** `/` 로 들어온 사람을 어디로 보낼지. */
export function landingEntryPath(storage: LandingSeenStorage | null | undefined): string {
  return readLandingSeen(storage) ? MAIN_PATH : INTRO_PATH
}
