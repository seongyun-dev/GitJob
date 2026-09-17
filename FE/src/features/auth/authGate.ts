/**
 * 보호 화면의 통과 판정 · 티켓 S15P21E102-303.
 *
 * <h2>왜 `null` 을 바로 로그아웃으로 읽으면 안 되나</h2>
 *
 * `fetchMe` 가 401 을 `null` 로 접기 때문에(`api/me.ts`) `null` 은 두 가지를 뜻한다 —
 * 정말 로그아웃이거나, 아직 확인되지 않은 이전 값이거나. 후자는 두 곳에서 실제로 생긴다.
 *
 *   1. 공개 화면에서 캐시된 `null` 을 안고 보호 화면으로 넘어갈 때
 *   2. `sessionSync` 의 `refreshSessionCache` 가 다른 탭의 세션 변경을 받아 캐시를 비우고
 *      쿠키의 현재 소유자를 다시 읽는 동안
 *
 * 그 순간을 로그아웃으로 읽으면 로그인한 사용자가 `/login` 으로 튀었다가 돌아온다.
 * 그래서 **가드가 직접 한 번 확인해 확정된 뒤에만** `null` 을 로그아웃으로 본다.
 *
 * <h2>왜 "확정"을 밖에서 받나</h2>
 *
 * react-query 의 `isFetching` · `isFetchedAfterMount` 로는 가를 수 없다. 캐시된 `null` 을
 * 안고 마운트한 첫 렌더에서는 값이 `null` 이고 마운트 재조회는 아직 시작 전이라 둘 다
 * 로그아웃과 구분되지 않는다(2026-09-17 브라우저 QA 에서 실제로 `/login` 으로 튀었다).
 *
 * 그래서 가드가 마운트할 때 `/me` 를 직접 한 번 읽고, 그 조회가 끝났는지를 `settled` 로
 * 넘긴다. 티켓 302 가 관리자 로그인에서 쓴 것과 같은 방법이다 — 캐시의 신선도를 믿지
 * 않고 확정적으로 읽는다.
 *
 * 반대 방향도 지킨다. 이미 확인된 사용자는 확정을 기다리지 않고 바로 통과시킨다 —
 * `useMe` 가 창 포커스마다 `/me` 를 다시 확인하므로(`refetchOnWindowFocus`), 그때마다
 * 화면을 내리면 탭을 옮길 때마다 보호 화면이 깜빡인다.
 *
 * <h2>왜 순수 함수인가</h2>
 *
 * 이 판정이 틀리면 로그인한 사람이 쫓겨나거나 로그인하지 않은 사람이 들어온다. 화면을
 * 띄우지 않고 표로 검증할 수 있어야 하는 규칙이라 컴포넌트 밖에 둔다. 아무것도 import
 * 하지 않는 이유는 `@/` 별칭을 Vite 가 풀기 때문이다 — 별칭을 쓰면 `node --test` 에서
 * 해석되지 않는다.
 *
 * 이것은 UX 계층이다. 실제 접근 제한은 BE `SecurityConfig` 가 계속 담당한다.
 */

export type AuthGate =
  /** 아직 판단할 수 없다. 화면도 이동도 하지 않고 기다린다. */
  | 'LOADING'
  /** 보호 화면을 그린다. */
  | 'ALLOW'
  /** 로그인 화면으로 보낸다. */
  | 'REDIRECT'

export interface AuthGateInput {
  /** `/me` 결과. `undefined` 는 확인 전, `null` 은 로그아웃, 값이 있으면 로그인이다. */
  me: { userId: string } | null | undefined
  /**
   * 가드가 마운트하며 직접 건 `/me` 조회가 끝났는가.
   *
   * 캐시에 남아 있던 값과 방금 확인한 값을 가르는 신호다. 성공이든 실패든 끝나면 `true`.
   */
  settled: boolean
  /**
   * 그 확인이 실패했는가(네트워크·5xx). 401 은 여기 해당하지 않는다 — `fetchMe` 가
   * `null` 로 접는다.
   */
  failed?: boolean
}

export function authGate({ me, settled, failed = false }: AuthGateInput): AuthGate {
  /*
    이미 아는 사용자는 확정을 기다리지 않는다. 기다리게 하면 보호 화면 사이를 오갈
    때마다 로딩이 한 번씩 끼어든다.
  */
  if (me !== null && me !== undefined) {
    return 'ALLOW'
  }
  if (!settled) {
    return 'LOADING'
  }
  /*
    확인이 끝났는데도 값이 없다. `null` 이면 로그아웃이고, `undefined` 인 채로 실패했으면
    로그아웃인지 알 수 없다 — 기다리게 두면 화면이 영영 비어 있으므로 로그인 화면으로
    접는다. 그쪽에는 되돌아올 길이 있다.
  */
  if (me === null || failed) {
    return 'REDIRECT'
  }
  return 'LOADING'
}
