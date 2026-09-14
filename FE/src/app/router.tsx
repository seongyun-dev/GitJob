import { createBrowserRouter } from 'react-router'
import { AppLayout } from '@/app/layouts/AppLayout'
import { RootLayout } from '@/app/layouts/RootLayout'
import { NotFoundPage } from '@/app/pages/NotFoundPage'
import { SystemStatesPage } from '@/app/pages/SystemStatesPage'
import { TeamPage } from '@/features/about/pages/TeamPage'
import { AdminLayout } from '@/features/admin/layouts/AdminLayout'
import { SystemMonitoringPage } from '@/features/admin/monitoring/pages/SystemMonitoringPage'
import { TechnologyCandidatePage } from '@/features/admin/pages/TechnologyCandidatePage'
import { AnalysisProgressPage } from '@/features/analysis/pages/AnalysisProgressPage'
import { RepositorySelectionPage } from '@/features/analysis/pages/RepositorySelectionPage'
import { AuthCallbackPage } from '@/features/auth/pages/AuthCallbackPage'
import { GithubConnectPage } from '@/features/auth/pages/GithubConnectPage'
import { EvidenceDetailPage } from '@/features/evidence/pages/EvidenceDetailPage'
import { EvidenceOverviewPage } from '@/features/evidence/pages/EvidenceOverviewPage'
import { LandingPage } from '@/features/landing/pages/LandingPage'
import { PrivacyPolicyPage } from '@/features/legal/pages/PrivacyPolicyPage'
import { SkillGapPage } from '@/features/matching/pages/SkillGapPage'
import { TargetRolePage } from '@/features/matching/pages/TargetRolePage'
import { WhatIfPage } from '@/features/matching/pages/WhatIfPage'
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
 *
 * 155·156은 GitHub 연결 화면(Final v2 `#connect`)이고 이 브랜치에서 만들었다. 192의
 * 주석은 155·156이 로그인 화면까지 소유한다고 적었는데 Jira 확인 결과 아니었다.
 * Final v2 `02 SSAFY Login`에 해당하는 로그인 전용 화면은 아직 소유 티켓을 모른다.
 *
 * 라우터 인스턴스를 내보내는 이유는 React 밖에서도 이동해야 하기 때문이다 — 쿼리
 * 실패를 한곳에서 받아 GitHub 재연결 화면으로 보내는 데 쓴다(`app/providers.tsx`).
 * 같은 파일에서 컴포넌트를 함께 내보내면 Fast Refresh가 동작하지 않으므로
 * `RouterProvider`는 `main.tsx`에 둔다.
 */
export const router = createBrowserRouter([
  /*
   * 경로 없는 최상위 레이아웃. 화면을 그리지 않고 이동할 때 스크롤을 맨 위로
   * 돌리는 일만 한다 — 이유는 `RootLayout`에 적었다.
   *
   * 경로가 없으므로 아래 라우트들의 URL은 그대로다. 랜딩·GitHub 연결처럼
   * `AppLayout` 밖에 있는 화면까지 한 번에 덮으려고 여기에 둔다.
   */
  {
    element: <RootLayout />,
    children: [
      // S1 Landing · 티켓 191. 배경이 화면 전체를 덮어야 해서 AppLayout 밖에 둔다.
      // 정적 경로가 splat보다 먼저 매칭되므로 아래 `*`가 `/`를 가로채지 않는다.
      { path: '/', element: <LandingPage /> },
      // 티켓 156. GitHub 토큰이 폐기·만료됐을 때 `providers.tsx` 전역 가드가 보내는 곳.
      // Final v2 `#connect`가 앱 내비게이션 없는 독립 화면이라 AppLayout 밖에 둔다.
      { path: '/onboarding/github', element: <GithubConnectPage /> },
      /*
       * 관리자 전용 · 티켓 210. 사용자 여정의 일부가 아니라 운영 화면이라 `AppLayout`이
       * 아닌 전용 셸을 쓴다. 확정 디자인 `Admin Monitoring v2`의 헤더가 `ADMIN` 배지와
       * 관리자 화면 두 개만 갖기 때문이다.
       *
       * `/`보다 앞에 둔다. 정적 세그먼트가 splat보다 먼저 매칭되므로 순서에 의존하지는
       * 않지만, 읽는 사람이 `admin/*`가 아래 `*` 404로 떨어지지 않는다는 것을 바로 알 수
       * 있게 한다.
       *
       * 기본 진입 화면(index)이 Monitoring이다. Technology Registry는 티켓 14에서 쓰던
       * `admin/technology-candidates` 경로를 그대로 유지한다 — 경로를 바꾸면 팀이
       * 공유해 둔 링크가 깨진다.
       *
       * 라우트를 숨기지 않는 이유는 숨겨도 보호가 되지 않기 때문이다. 접근 제어는 BE가
       * `/api/v1/admin/**`를 ADMIN으로 제한해서 한다.
       */
      {
        path: '/admin',
        element: <AdminLayout />,
        children: [
          { index: true, element: <SystemMonitoringPage /> },
          { path: 'technology-candidates', element: <TechnologyCandidatePage /> },
        ],
      },
      {
        path: '/',
        element: <AppLayout />,
        children: [
          // 티켓 156. 경로는 BE `github.oauth.frontend-callback-url`이 정한다.
          // 이 라우트가 없으면 로그인 성공 직후 `*`로 떨어져 404가 보인다.
          { path: 'auth/callback', element: <AuthCallbackPage /> },
          // 티켓 117. 백엔드 OAUTH_ALLOWED_REDIRECT_PATHS의 기본 목적지와 같은 경로다.
          { path: 'onboarding/repositories', element: <RepositorySelectionPage /> },
          // 초안 · 세부 기능은 티켓 136
          { path: 'analyses/:analysisId', element: <AnalysisProgressPage /> },
          // 초안 · 세부 기능은 티켓 137·138
          { path: 'evidence', element: <EvidenceOverviewPage /> },
          { path: 'evidence/:techId', element: <EvidenceDetailPage /> },
          // 티켓 204 · Final v2 16. Evidence → 직무 선택 → 공고 매칭 순서다.
          { path: 'roles', element: <TargetRolePage /> },
          { path: 'jobs', element: <JobMatchPage /> },
          // 티켓 204 · Final v2 17. 공고 매칭 다음, 추천 이전에 온다.
          { path: 'skill-gap', element: <SkillGapPage /> },
          { path: 'recommendations', element: <RecommendationPage /> },
          // 티켓 204 · Final v2 03. 추천에 접어 두지 않고 별도 화면으로 둔다.
          { path: 'what-if', element: <WhatIfPage /> },
          { path: 'technologies/:techId', element: <TechnologyDetailPage /> },
          { path: 'trends', element: <TrendPage /> },
          { path: 'trends/:techId', element: <TrendDetailPage /> },
          { path: 'mypage', element: <MyPage /> },

          // 티켓 204 · Final v2 15. 팀 내부 표기 레퍼런스라 헤더 네비게이션에는 넣지 않는다.
          { path: 'system-states', element: <SystemStatesPage /> },

          /*
           * 하단바가 가리키는 두 화면. 헤더 네비게이션에는 넣지 않는다 — 사용자 여정의
           * 단계가 아니라 상시 참조용이고, Final v2 헤더도 5개로 고정돼 있다.
           *
           * 로그인 전에도 열려야 한다. 랜딩 하단바에서 들어오는 경로이고, 처리방침은
           * 가입 여부와 무관하게 읽을 수 있어야 한다. 두 화면 모두 쿼리를 걸지 않아
           * `providers.tsx`의 인증 실패 가드에 걸리지 않는다.
           *
           * 전용 레이아웃을 새로 만들지 않고 `AppLayout`에 둔다. 로그인 전 방문자에게
           * 앱 헤더가 함께 보이지만, 헤더는 사용자 데이터를 쓰지 않아 그대로 그려진다.
           * 정적 화면 두 개를 위해 세 번째 셸을 만들 만한 차이가 아니다.
           */
          { path: 'privacy', element: <PrivacyPolicyPage /> },
          { path: 'team', element: <TeamPage /> },

          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
