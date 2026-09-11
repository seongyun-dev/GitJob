import type { RepositorySummary } from '@/features/analysis/api/types'

/**
 * `GET /me/repositories` 응답 fixture · 화면 06 Repository.
 *
 * **이 계약은 BE에 실제로 구현돼 있다**(`docs/fe/shared-api-contract.md` 1-4).
 * 다른 fixture와 성격이 다르므로 타입도 실제 계약(`RepositorySummary`)을 그대로
 * 쓴다. 이 화면에 fixture가 필요한 이유는 API가 없어서가 아니라, 목록을 보려면
 * BE와 GitHub OAuth 연결이 모두 살아 있어야 해서 레이아웃 작업의 진입 비용이
 * 크기 때문이다.
 *
 * 그래서 `withDesignFixture`로 감쌀 때 **로딩·오류 경로를 건너뛴다.** 디자인
 * fixture가 켜져 있다는 것은 "지금은 서버를 보지 않는다"는 명시적 선언이므로,
 * 그 상태에서 오류 패널을 함께 띄우면 무엇을 보고 있는지 알 수 없다.
 *
 * 값은 확정 디자인 아트보드 06에서 옮겼다. 다만 그 화면의 `Fork`·`Archived` 배지는
 * **계약에 대응 필드가 없다** — BE는 `analyzable` 한 값만 주고 그 값은
 * `archived || disabled`의 결과다(fork 여부는 들어 있지 않다). 그래서 `legacy-board`를
 * `analyzable: false`로 두었고, 화면이 두 배지를 따로 그릴 수는 없다.
 */
export const REPOSITORY_LIST: RepositorySummary[] = [
  {
    githubRepositoryId: 810234571,
    fullName: 'dev-user/GitJob',
    name: 'GitJob',
    owner: 'dev-user',
    isPrivate: false,
    defaultBranch: 'main',
    description: 'GitHub Evidence 기반 기술 판정 서비스',
    language: 'Java',
    updatedAt: '2026-09-08T12:31:00Z',
    analyzable: true,
  },
  {
    githubRepositoryId: 778120044,
    fullName: 'dev-user/RO-KI',
    name: 'RO-KI',
    owner: 'dev-user',
    isPrivate: true,
    defaultBranch: 'develop',
    description: '주문 이벤트 처리 실습 프로젝트',
    language: 'Java',
    updatedAt: '2026-08-28T04:12:00Z',
    analyzable: true,
  },
  {
    githubRepositoryId: 654993201,
    fullName: 'dev-user/algo-study',
    name: 'algo-study',
    owner: 'dev-user',
    isPrivate: false,
    defaultBranch: 'main',
    // 설명이 null인 저장소. GitHub이 null을 주므로 화면이 그 경우를 다뤄야 한다.
    description: null,
    language: 'Java',
    updatedAt: '2026-04-11T09:40:00Z',
    analyzable: true,
  },
  {
    githubRepositoryId: 512008877,
    fullName: 'dev-user/legacy-board',
    name: 'legacy-board',
    owner: 'dev-user',
    isPrivate: false,
    defaultBranch: 'master',
    description: '보관된 게시판 프로젝트',
    // 대표 언어가 없는 저장소도 온다.
    language: null,
    updatedAt: '2025-09-02T15:55:00Z',
    // 분석할 수 없는 저장소. 목록에서 어떻게 보이는지 확인할 자리다.
    analyzable: false,
  },
]
