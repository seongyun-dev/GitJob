import { createBrowserRouter, RouterProvider } from 'react-router'
import { AppLayout } from '@/app/layouts/AppLayout'
import { NotFoundPage } from '@/app/pages/NotFoundPage'
import { RepositorySelectionPage } from '@/features/analysis/pages/RepositorySelectionPage'

/**
 * 이번 스프린트 티켓에 해당하는 라우트만 둔다.
 * S9(파이프라인 운영)는 A조 소유이므로 라우트를 만들지 않는다.
 */
const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      // S1 온보딩 화면 티켓이 생기기 전까지의 임시 처리. `*`는 부모 경로 자체(/)에는
      // 매칭되지 않아 index 라우트가 없으면 빈 화면이 된다. 빈 화면 대신 404를 보여준다.
      { index: true, element: <NotFoundPage /> },
      // S2 · 티켓 117. 백엔드 OAUTH_ALLOWED_REDIRECT_PATHS의 기본 목적지와 같은 경로다.
      { path: 'onboarding/repositories', element: <RepositorySelectionPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export function AppRouter() {
  return <RouterProvider router={router} />
}
