import type { PageParams } from '@/shared/types/api'

/**
 * 캐시 키 규약의 구현 (설계 §4-1).
 *
 * 증거 계열과 매칭 계열을 나누는 것이 핵심이다.
 * 증거는 analysisId에 묶이면 불변이므로 목표 직무를 바꿔도 살아 있어야 하고,
 * 매칭은 목표 직무가 키의 일부라 직무가 바뀌면 키가 달라져 자동 무효화된다.
 *
 * 이 분리가 있어야 "깃허브를 다시 읽지 않으므로 즉시 계산됩니다"가 성립한다.
 *
 * 어느 키가 실제로 BE에 있는지는 docs/fe/shared-api-contract.md 1-4.
 * 저장소 목록·브랜치만 구현되어 있고 나머지는 아직 엔드포인트가 없다.
 */

/** 증거 계열은 analysisId가 같으면 서버 응답이 바뀌지 않는다. */
export const EVIDENCE_STALE_TIME = Number.POSITIVE_INFINITY

export const queryKeys = {
  me: () => ['me'] as const,

  // 저장소 계열 — 사용자 GitHub 상태에 따라 변하므로 기본 staleTime을 쓴다.
  // 목록 필터(sort·q·includeForks 등)는 BE에 없어 페이징만 키에 넣는다.
  repositories: (params: PageParams) => ['repositories', 'list', params] as const,
  repositoryBranches: (fullName: string, params: PageParams) =>
    ['repositories', 'branches', fullName, params] as const,
  repositorySelection: () => ['repositories', 'selection'] as const,

  // 증거 계열 — analysisId에 묶이면 불변
  analysis: (analysisId: string) => ['analysis', analysisId] as const,
  analysisProfile: (analysisId: string) => ['analysis', analysisId, 'profile'] as const,
  analysisEvidence: (analysisId: string, techId: string) =>
    ['analysis', analysisId, 'evidence', techId] as const,
  analysisRepositories: (analysisId: string) =>
    ['analysis', analysisId, 'repositories'] as const,

  // 내 기술 판정. analysisId 가 아니라 사용자 단위다 -- BE 가 저장소별 최신 성공
  // 분석을 모아 집계하므로 화면이 analysisId 를 알 필요가 없다. 분석이 하나 더
  // 끝나면 결과가 달라지므로 무한 staleTime 을 쓰지 않는다.
  myTechnologies: () => ['me', 'technologies'] as const,
  myTechnologyEvidence: (techId: string) => ['me', 'technologies', techId, 'evidence'] as const,

  // 관리자 — 후보 목록과 레지스트리 상태. 승격·거절이 둘 다 바꾸므로
  // 한 뮤테이션이 두 키를 모두 무효화한다.
  technologyCandidates: (limit: number) => ['admin', 'technology-candidates', limit] as const,
  registryStatus: () => ['admin', 'registry'] as const,

  // 관리자 모니터링 — 티켓 210. `admin` 접두를 공유하므로 후보 검토의 뮤테이션이
  // 무효화하는 `['admin']` 범위에 함께 들어간다. 모니터링은 뮤테이션이 없고 주기
  // 갱신만 하므로 그 무효화가 해가 되지 않는다.
  monitoringOverview: () => ['admin', 'monitoring', 'overview'] as const,
  monitoringTimeseries: (metric: string) =>
    ['admin', 'monitoring', 'timeseries', metric] as const,

  // 매칭 계열 — target이 키의 일부
  matching: (analysisId: string, target: unknown) => ['matching', analysisId, target] as const,
  matchingSkillGap: (analysisId: string, target: unknown) =>
    ['matching', analysisId, target, 'skill-gap'] as const,
  matchingPostings: (analysisId: string, target: unknown) =>
    ['matching', analysisId, target, 'postings'] as const,
} as const
