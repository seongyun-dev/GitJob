import { createBrowserRouter, RouterProvider } from 'react-router'
import { AppLayout } from '@/app/layouts/AppLayout'
import { NotFoundPage } from '@/app/pages/NotFoundPage'
import { TechnologyCandidatePage } from '@/features/admin/pages/TechnologyCandidatePage'
import { AnalysisProgressPage } from '@/features/analysis/pages/AnalysisProgressPage'
import { RepositorySelectionPage } from '@/features/analysis/pages/RepositorySelectionPage'
import { EvidenceDetailPage } from '@/features/evidence/pages/EvidenceDetailPage'
import { EvidenceOverviewPage } from '@/features/evidence/pages/EvidenceOverviewPage'
import { LandingPage } from '@/features/landing/pages/LandingPage'
import { JobMatchPage } from '@/features/matching/pages/JobMatchPage'
import { RecommendationPage } from '@/features/matching/pages/RecommendationPage'
import { MyPage } from '@/features/mypage/pages/MyPage'
import { TechnologyDetailPage } from '@/features/technology/pages/TechnologyDetailPage'
import { TrendDetailPage } from '@/features/trend/pages/TrendDetailPage'
import { TrendPage } from '@/features/trend/pages/TrendPage'

/**
 * 라우트 구성 · 티켓 S15P21E102-192에서 전체 화면으로 확장.
 *
 * 경로 이름은 새로 만든 규칙이 아니라 이미 있는 것들을 따랐다.
 *   - `/`, `/onboarding/repositories`: 티켓 191·117에서 쓰던 경로 그대로.
 *     후자는 백엔드 `OAUTH_ALLOWED_REDIRECT_PATHS`의 기본 목적지와 같아야 한다.
 *   - `/analyses/:analysisId`: BE가 돌려주는 `statusUrl`이 `/api/v1/analyses/{id}`라
 *     화면 경로도 같은 자원 이름을 쓴다.
 *   - `/evidence/:techId`, `/technologies/:techId`: `shared/api/queryKeys`의
 *     `analysisEvidence(analysisId, techId)`와 설계 문서의 `/me/technologies/{techId}`
 *     명칭에 맞췄다.
 *   - `/jobs`, `/recommendations`, `/trends`, `/mypage`: 설계 문서 3장 화면 목록의
 *     이름을 따랐다.
 *
 * S9(파이프라인 운영)는 A조 소유이므로 라우트를 만들지 않는다.
 * 로그인·GitHub 연결 화면(Final `#login`·`#connect`)은 Auth 정책이 확정되지 않았고
 * 별도 티켓(155·156) 소유라 이 초안에서 만들지 않는다.
 */
const router = createBrowserRouter([
  // S1 Landing · 티켓 191. 배경이 화면 전체를 덮어야 해서 AppLayout 밖에 둔다.
  // 정적 경로가 splat보다 먼저 매칭되므로 아래 `*`가 `/`를 가로채지 않는다.
  { path: '/', element: <LandingPage /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      // 티켓 117. 백엔드 OAUTH_ALLOWED_REDIRECT_PATHS의 기본 목적지와 같은 경로다.
      { path: 'onboarding/repositories', element: <RepositorySelectionPage /> },
      // 초안 · 세부 기능은 티켓 136
      { path: 'analyses/:analysisId', element: <AnalysisProgressPage /> },
      // 초안 · 세부 기능은 티켓 137·138
      { path: 'evidence', element: <EvidenceOverviewPage /> },
      { path: 'evidence/:techId', element: <EvidenceDetailPage /> },
      { path: 'jobs', element: <JobMatchPage /> },
      { path: 'recommendations', element: <RecommendationPage /> },
      { path: 'technologies/:techId', element: <TechnologyDetailPage /> },
      { path: 'trends', element: <TrendPage /> },
      { path: 'trends/:techId', element: <TrendDetailPage /> },
      { path: 'mypage', element: <MyPage /> },

      // 관리자 전용. 위 경로들과 달리 사용자 여정의 일부가 아니라 운영 화면이다.
      // 라우트를 숨기지 않는 이유는 숨겨도 보호가 되지 않기 때문이다. 접근
      // 제어는 BE가 /api/v1/admin/** 를 ADMIN 으로 제한해서 한다.
      { path: 'admin/technology-candidates', element: <TechnologyCandidatePage /> },

      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export function AppRouter() {
  return <RouterProvider router={router} />
}
