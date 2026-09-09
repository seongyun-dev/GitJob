import { createBrowserRouter, RouterProvider } from 'react-router'
import { AppLayout } from '@/app/layouts/AppLayout'
import { NotFoundPage } from '@/app/pages/NotFoundPage'
import { RepositorySelectionPage } from '@/features/analysis/pages/RepositorySelectionPage'
import { LandingPage } from '@/features/landing/pages/LandingPage'

/**
 * 이번 스프린트 티켓에 해당하는 라우트만 둔다.
 * S9(파이프라인 운영)는 A조 소유이므로 라우트를 만들지 않는다.
 */
const router = createBrowserRouter([
  // S1 Landing · 티켓 191. 배경이 화면 전체를 덮어야 해서 AppLayout 밖에 둔다.
  // 정적 경로가 splat보다 먼저 매칭되므로 아래 `*`가 `/`를 가로채지 않는다.
  { path: '/', element: <LandingPage /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      // S2 · 티켓 117. 백엔드 OAUTH_ALLOWED_REDIRECT_PATHS의 기본 목적지와 같은 경로다.
      { path: 'onboarding/repositories', element: <RepositorySelectionPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export function AppRouter() {
  return <RouterProvider router={router} />
}
