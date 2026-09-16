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
 * 매칭 계열의 실제 계약은 docs/be/c-compute-public-api.md다. 그 계열의 요청에는
 * analysisId도 snapshotId도 들어가지 않는다 -- 어느 계산 결과를 읽을지는 BE가
 * 로그인 사용자와 저장된 목표 직무로 정한다.
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
  technologyCandidates: (limit: number, status: string) =>
    ['admin', 'technology-candidates', limit, status] as const,
  technologyCandidateDetail: (candidateId: number) =>
    ['admin', 'technology-candidates', 'detail', candidateId] as const,
  technologyOptions: () => ['admin', 'technologies'] as const,
  registryStatus: () => ['admin', 'registry'] as const,

  // 관리자 모니터링 — 티켓 210. `admin` 접두를 공유하므로 후보 검토의 뮤테이션이
  // 무효화하는 `['admin']` 범위에 함께 들어간다. 모니터링은 뮤테이션이 없고 주기
  // 갱신만 하므로 그 무효화가 해가 되지 않는다.
  monitoringOverview: () => ['admin', 'monitoring', 'overview'] as const,
  monitoringTimeseries: (metric: string) =>
    ['admin', 'monitoring', 'timeseries', metric] as const,

  // 매칭 계열 -- 서버가 만든 targetKey가 키의 일부다.
  //
  // analysisId를 키에서 뺐다(S15P21E102-279). 요청이 analysisId도 snapshotId도
  // 보내지 않기 때문이다 -- 어느 계산 결과를 읽을지는 BE가 로그인 사용자와 목표
  // 직무로 정한다. 화면이 식별자를 들고 다니면 그것을 바꿔 보내는 경로가 생긴다.
  //
  // -281이 같은 결론에 먼저 닿았다("경로에 analysisId가 없다"). 다른 점은 키 재료뿐이며,
  // roleId 대신 targetKey를 쓰는 이유는 지역·경력까지 바뀌면 비교 집합이 달라지기
  // 때문이다. targetKey는 `GET /me/target`이 주는 정규화 문자열이고(`BACKEND|서울|신입`)
  // FE가 조합하지 않는다 -- 공백과 순서 차이로 같은 조건에 캐시가 두 벌 생긴다.
  target: () => ['me', 'target'] as const,
  matching: (targetKey: string) => ['matching', targetKey] as const,
  matchingPostings: (targetKey: string, params: PageParams & { includeConditional?: boolean }) =>
    ['matching', targetKey, 'postings', params] as const,
  matchingPosting: (targetKey: string, jobId: string) =>
    ['matching', targetKey, 'postings', jobId] as const,
  matchingSkillGap: (targetKey: string) => ['matching', targetKey, 'skill-gap'] as const,
  matchingRecommendations: (targetKey: string) =>
    ['matching', targetKey, 'recommendations'] as const,
  matchingWhatIf: (targetKey: string, techId: string, params: PageParams) =>
    ['matching', targetKey, 'what-if', techId, params] as const,

  // 시장 지표 -- 개인 결과가 아니라 사용자 단위로 나뉘지 않는다.
  jobDemands: (targetRole: string, regions: readonly string[], careerLevels: readonly string[]) =>
    ['job-demands', targetRole, regions, careerLevels] as const,
  technologyTrends: (
    techId: string,
    periods: readonly string[],
    targetKey: string | undefined,
  ) => ['trends', 'technology', techId, periods, targetKey] as const,
  trendCompare: (
    source: string,
    techIds: readonly string[],
    periods: readonly string[],
    targetKey: string | undefined,
  ) => ['trends', 'compare', source, techIds, periods, targetKey] as const,

  /*
   * 아직 조회 API가 없는 화면 · 티켓 S15P21E102-281.
   *
   * 분석 이력과 기술 단건 학습 자료는 -279 범위 밖이라 엔드포인트가 없다. 키만 먼저
   * 두는 이유는 화면이 붙을 자리를 고정해 두기 위해서이며, 지금 부르면 `HTTP-404`로
   * 끝나고 화면은 기존 상태 카드를 그린다.
   */
  myAnalyses: (params: unknown) => ['me', 'analyses', params] as const,
  projectTemplates: (techId: string) => ['technologies', techId, 'project-templates'] as const,
  technologyFaqs: (techId: string) => ['technologies', techId, 'faqs'] as const,
  technologyPainTopics: (techId: string) => ['technologies', techId, 'pain-topics'] as const,
} as const
