import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation } from 'react-router'
import { fetchMe } from '@/features/auth/api/me'
import { authGate } from '@/features/auth/authGate'
import { ME_QUERY_KEY, useMe } from '@/features/auth/hooks/useMe'
import { browserReturnToStorage, rememberReturnTo } from '@/features/auth/returnTo'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 로그인이 필요한 화면 묶음의 문 · 티켓 S15P21E102-303.
 *
 * <h2>왜 경로 없는 라우트 하나인가</h2>
 *
 * 화면마다 로그인 검사를 넣으면 새 화면을 만들 때 빠뜨리고, 빠뜨린 것은 그 화면을 열어
 * 보기 전까지 드러나지 않는다. `AppLayout` 안에 경로 없는 라우트로 한 번만 두고 보호
 * 화면을 그 아래로 옮긴다. URL 은 달라지지 않고 셸(헤더·하단바)도 하나만 유지된다.
 *
 * 헤더 내비게이션은 비로그인 상태에서도 숨기거나 비활성으로 만들지 않는다. 눌러 보고
 * 왜 막혔는지 아는 편이, 메뉴가 통째로 사라져 서비스가 고장 난 것처럼 보이는 것보다 낫다.
 *
 * `/admin/*` 은 이 아래에 두지 않는다. 기존 `AdminLayout` 의 role guard 를 그대로 쓰고,
 * 둘을 겹치면 관리자 로그인 직후 두 가드가 각자 판단해 서로 다른 곳으로 보낸다.
 *
 * <h2>판단은 밖에 있다</h2>
 *
 * 세 갈래(기다림·통과·이동)를 고르는 규칙은 {@link authGate} 가 갖는다. 틀리면 로그인한
 * 사람이 쫓겨나거나 로그인하지 않은 사람이 들어오는 규칙이라, 화면 없이 표로 검증할 수
 * 있어야 한다. 여기서는 그 결과를 화면으로 옮기기만 한다.
 *
 * 프론트엔드 가드는 UX 계층이다. 실제 접근 제한은 BE `SecurityConfig` 의
 * `anyRequest().authenticated()` 가 계속 담당한다. 라우트를 막는다고 API 보호를
 * 완화하지 않는다.
 */
export function RequireAuth() {
  const { data: me } = useMe()
  const location = useLocation()

  /*
    붙을 때 `/me` 를 한 번 확정적으로 읽는다 · 티켓 303.

    캐시 값만 보고 판단할 수 없다. 공개 화면에서 캐시된 `null` 을 안고 넘어오면 첫
    렌더에서 값은 `null` 이고 마운트 재조회는 아직 시작 전이라, react-query 의
    `isFetching` · `isFetchedAfterMount` 로는 로그아웃과 구분되지 않는다. 그대로 두면
    로그인한 사용자도 확인 없이 `/login` 으로 튄다(2026-09-17 브라우저 QA).

    `fetchQuery` 는 관측자 유무·캐시 신선도와 무관하게 읽고 결과를 캐시에 직접 쓴다.
    티켓 302 가 관리자 로그인에서 같은 이유로 쓴 방법이다. 읽기 결과는 위의 `useMe` 로
    들어오므로 여기서는 **끝났는지**와 **실패했는지**만 남긴다.

    보호 화면 사이를 오갈 때는 다시 돌지 않는다 — 이 컴포넌트가 보호 구역의 라우트라
    구역 안에서 화면을 옮겨도 마운트를 유지한다.
  */
  const queryClient = useQueryClient()
  const [check, setCheck] = useState({ settled: false, failed: false })

  useEffect(() => {
    let alive = true
    queryClient
      .fetchQuery({ queryKey: ME_QUERY_KEY, queryFn: fetchMe })
      .then(() => {
        if (alive) {
          setCheck({ settled: true, failed: false })
        }
      })
      .catch(() => {
        // 401 은 여기 오지 않는다 — `fetchMe` 가 `null` 로 접는다. 네트워크·5xx 뿐이다.
        if (alive) {
          setCheck({ settled: true, failed: true })
        }
      })
    return () => {
      alive = false
    }
  }, [queryClient])

  const gate = authGate({ me, settled: check.settled, failed: check.failed })

  if (gate === 'ALLOW') {
    return <Outlet />
  }

  if (gate === 'LOADING') {
    /*
      기다리는 동안 아무것도 그리지 않으면 화면이 잠깐 비어 "빈 페이지가 떴다"로 읽힌다.
      `StateCard` 가 이 앱의 조회 중 상태 어휘이고 `role="status"` 도 갖고 있다.
    */
    return (
      <StateCard
        kind="LOADING"
        title="로그인 상태를 확인하고 있습니다"
        description="잠시 후 화면이 이어집니다."
      />
    )
  }

  /*
    가려던 자리를 적어 두고 로그인 화면으로 보낸다. 로그인 뒤 `/auth/callback` 이 이 값을
    한 번 꺼내 쓴다(`returnTo.ts`).

    렌더 중에 적는 것은 이 분기가 곧바로 화면을 떠나기 때문이다. 효과로 미루면 이동이
    먼저 일어나 적을 기회가 없다. 같은 값을 여러 번 적어도 결과가 같은 쓰기라 안전하다.

    `replace` 인 이유는 뒤로 가기가 막힌 화면으로 돌아오지 않게 하기 위해서다. 그 화면은
    다시 여기로 보내므로 뒤로 가기가 듣지 않는 것처럼 보인다.

    목적지를 `?redirectTo=` 로 싣지 않는다. 그 쿼리는 BE OAuth 허용 목록으로 흘러가고,
    허용 목록에 없는 서비스 경로를 실으면 `AUTH-400-1` 이 난다(`returnTo.ts` 주석).
  */
  rememberReturnTo(browserReturnToStorage(), location)
  return <Navigate to="/login" replace />
}
