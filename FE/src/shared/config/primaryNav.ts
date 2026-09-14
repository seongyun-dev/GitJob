/**
 * 헤더 공통 내비게이션 · 티켓 S15P21E102-246.
 *
 * 랜딩 헤더와 로그인 후 내부 헤더가 **같은 이름·순서·개수·목적지**를 쓰도록 한곳에서
 * 정의한다. 이전에는 랜딩(`landingPreviewData.LANDING_NAV`, 4개)과 내부
 * (`AppHeader` 인라인, 5개+마이페이지)가 따로여서 서비스가 분리된 것처럼 보였다.
 *
 * `intro`(서비스 소개)만 라우트가 아니라 랜딩의 섹션 앵커라 종류를 나눈다. 랜딩에서는
 * 같은 페이지 스크롤, 내부 페이지에서는 랜딩으로 이동 후 그 섹션으로 간다. 나머지는
 * 모두 실재하는 라우트다(`app/router.tsx`).
 *
 * "GitHub 분석"은 분석 시작 지점(`/onboarding/repositories`)으로 통일했다(2026-09-13 결정).
 * 마이페이지는 이 목록에서 뺀다 — 상단이 아니라 프로필 드롭다운에 들어간다.
 */

export type PrimaryNavItem =
  | { readonly label: string; readonly kind: 'intro' }
  | { readonly label: string; readonly to: string }

export const SERVICE_INTRO_HASH = '#service-intro'

export const PRIMARY_NAV: readonly PrimaryNavItem[] = [
  { label: '서비스 소개', kind: 'intro' },
  { label: 'GitHub 분석', to: '/onboarding/repositories' },
  { label: '채용공고 매칭', to: '/jobs' },
  { label: '다음 기술', to: '/recommendations' },
  { label: '기술 트렌드', to: '/trends' },
]
