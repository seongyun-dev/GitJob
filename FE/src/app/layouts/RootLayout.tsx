import { Outlet, ScrollRestoration } from 'react-router'

/**
 * 모든 라우트를 감싸는 경로 없는 레이아웃. 화면을 그리지 않고 이동할 때의 스크롤
 * 위치만 맡는다.
 *
 * `createBrowserRouter`는 이동해도 스크롤을 건드리지 않는다. 브라우저의 기본 스크롤
 * 복원은 문서를 다시 불러올 때만 동작하고, SPA 안에서의 이동은 문서가 그대로라
 * 이전 위치가 남는다.
 *
 * 그래서 하단바에서 다른 화면으로 가면 바닥에 있던 스크롤이 그대로 유지돼, 새 화면이
 * 열렸는데도 화면에는 다시 하단바가 보인다. 이동이 안 된 것처럼 읽히지만 실제로는
 * 이동한 뒤 아래쪽을 보고 있는 것이다.
 *
 * `ScrollRestoration`이 이동 종류에 따라 갈라 준다.
 *   - 링크로 새로 들어가면(PUSH·REPLACE) 맨 위
 *   - 뒤로·앞으로 가면(POP) 그 화면에서 보던 위치
 *
 * 직접 `window.scrollTo(0, 0)`을 걸면 뒤로 가기도 맨 위로 가서, 긴 목록을 읽다가
 * 상세로 들어갔다 돌아왔을 때 읽던 자리를 잃는다.
 *
 * 위치는 `location.key`별로 `sessionStorage`에 저장된다. 탭을 닫으면 사라지고 다른
 * 탭과 섞이지 않는다.
 *
 * 랜딩(`.lp-scroll`)은 문서가 아니라 자기 컨테이너가 스크롤하므로 여기 대상이
 * 아니다. 이동할 때 통째로 새로 붙어 항상 0에서 시작하고, 랜딩 안쪽 앵커 이동은
 * 주소를 바꾸지 않아(`scrollToHash.ts`) 이 복원과 마주치지 않는다.
 */
export function RootLayout() {
  return (
    <>
      <ScrollRestoration />
      <Outlet />
    </>
  )
}
