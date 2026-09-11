import type {
  AnalysisHistoryFixture,
  AnalysisRepoProgressFixture,
  AnalysisStepFixture,
  RepositoryFixture,
} from '@/mocks/types'
import type { EvidenceLevel, JobStatus } from '@/shared/types/domain'

/**
 * 저장소 선택 · 분석 진행 · 마이페이지 fixture · 화면 06·07·14.
 *
 * 세 화면이 같은 저장소 셋을 공유하므로 한 파일에 둔다. 저장소 이름이 화면마다
 * 다르면 같은 분석을 보고 있다는 느낌이 깨진다.
 */

/**
 * 선택 가능한 저장소 · 화면 06.
 *
 * `legacy-board`에 `Fork`·`Archived`를 둘 다 붙인 것이 의도다. 배지가 하나일 때와
 * 둘일 때 카드 높이가 달라지는지 봐야 하고, 오래된 저장소가 목록에서 어떻게 보이는지도
 * 확인해야 한다.
 */
export const SELECTABLE_REPOSITORIES: RepositoryFixture[] = [
  {
    id: 'gitjob',
    name: 'GitJob',
    meta: 'Java · Spring Boot · main',
    lastPushText: '최근 push 3일 전',
    flags: [],
    selected: true,
  },
  {
    id: 'roki',
    name: 'RO-KI',
    meta: 'Java · Python · develop',
    lastPushText: '최근 push 2주 전',
    flags: [],
    selected: true,
  },
  {
    id: 'algo-study',
    name: 'algo-study',
    meta: 'Java · main',
    lastPushText: '최근 push 5개월 전',
    flags: [],
    selected: false,
  },
  {
    id: 'legacy-board',
    name: 'legacy-board',
    meta: 'JavaScript · master',
    lastPushText: '최근 push 1년 전',
    flags: ['Fork', 'Archived'],
    selected: false,
  },
]

/** 분석 단계 · 화면 07. 넷 중 둘 완료 · 하나 진행 · 하나 대기 상태다. */
export const ANALYSIS_STEPS: AnalysisStepFixture[] = [
  {
    no: 'STEP 01',
    title: '저장소 확인',
    description: 'Repository 메타데이터 · 브랜치 · 권한',
    progressText: '3개 확인',
    state: 'DONE',
  },
  {
    no: 'STEP 02',
    title: '파일 구조 분석',
    description: '빌드 · 설정 · 소스 파일 분류',
    progressText: '1,284개 파일',
    state: 'DONE',
  },
  {
    no: 'STEP 03',
    title: 'Evidence 판정',
    description: 'Dependency → 설정 → 구현 순으로 Level 판정',
    progressText: '기술 14개 검토 중',
    state: 'RUNNING',
  },
  {
    no: 'STEP 04',
    title: '사용자 기여 확인',
    description: 'Commit 작성자 대조 → Personal Level 확정',
    progressText: '대기',
    state: 'WAITING',
  },
]

/** 저장소별 진행 · 화면 07 우측. */
export const ANALYSIS_REPO_PROGRESS: AnalysisRepoProgressFixture[] = [
  {
    name: 'GitJob',
    meta: 'Java · Spring Boot · main',
    statusText: '완료 · 기술 11 확인',
    state: 'DONE',
  },
  {
    name: 'RO-KI',
    meta: 'Java · Python · develop',
    statusText: '분석 중 · 파일 612 / 984',
    state: 'RUNNING',
  },
  { name: 'algo-study', meta: 'Java · main', statusText: '대기', state: 'WAITING' },
]

/**
 * 진행 상태 · 화면 07.
 *
 * `RATE_LIMITED`가 종료 상태가 아니라는 점이 화면에도 그대로 나와야 한다
 * (`isTerminalJobStatus`). 진행률이 유지되고 부분 결과도 남는다.
 *
 * 두 변형에 같은 타입을 붙이는 이유는 화면이 둘을 한 값으로 다뤄야 하기 때문이다.
 * 추론에 맡기면 `status`가 리터럴로 좁혀져 상태 전환이 타입 오류가 된다.
 */
export interface AnalysisProgressFixture {
  status: JobStatus
  title: string
  statusText: string
  progressPercent: number
  /** 한도 대기 같은 추가 안내. 없으면 null. */
  banner: string | null
}

export const ANALYSIS_RUNNING: AnalysisProgressFixture = {
  status: 'RUNNING',
  title: 'GitHub를 분석하고 있어요',
  statusText: '3개 Repository 중 2개 분석 완료 · 약 1분 남음',
  progressPercent: 72,
  banner: null,
}

export const ANALYSIS_RATE_LIMITED: AnalysisProgressFixture = {
  status: 'RATE_LIMITED',
  title: 'GitHub 호출 한도를 기다리고 있어요',
  statusText: '14:25에 자동으로 다시 시작됩니다 · 부분 결과 유지',
  progressPercent: 72,
  banner:
    'GitHub 호출 한도를 기다리고 있어요. 14:25에 자동으로 다시 시작됩니다. 지금까지 확보한 부분 결과는 그대로 유지됩니다.',
}

/**
 * 진행 중 부분 결과 · 화면 07 우측.
 *
 * Repository 기준 중간 결과라 Personal Level이 아직 없다. 완료 화면(08)의 표와 같은
 * 컴포넌트를 쓰고 싶어지는 자리인데, 축이 하나뿐이라 그대로 쓰면 안 된다.
 */
export const ANALYSIS_PARTIAL_RESULT: { techName: string; repoLevel: EvidenceLevel }[] = [
  { techName: 'Java', repoLevel: 'L3' },
  { techName: 'Spring Boot', repoLevel: 'L2' },
  { techName: 'Redis', repoLevel: 'L2' },
  { techName: 'Docker', repoLevel: 'L1' },
]

export const ANALYSIS_PARTIAL_NOTE =
  'Repository 기준 중간 결과입니다. Personal Level은 STEP 04 사용자 기여 확인 후 확정됩니다.'

/**
 * 분석 이력 · 화면 14.
 *
 * 네 줄의 상태가 모두 다르다(SUCCEEDED 둘 · PARTIAL · FAILED). 실패와 부분 완료를
 * 같은 색으로 칠하면 안 된다는 것이 화면 15의 규칙이므로, 이력 표에서도 그 구분이
 * 실제로 보이는지 확인할 수 있어야 한다.
 */
export const ANALYSIS_HISTORY: AnalysisHistoryFixture[] = [
  {
    at: '오늘 10:42',
    repositories: 'GitJob · RO-KI · algo-study',
    resultText: '기술 14 · L2 이상 6',
    status: 'SUCCEEDED',
  },
  {
    at: '8월 3일 21:10',
    repositories: 'GitJob · RO-KI',
    resultText: '기술 11 · RO-KI 분석 중 RATE_LIMITED 후 부분 완료',
    status: 'PARTIAL',
  },
  {
    at: '7월 12일 09:31',
    repositories: 'GitJob',
    resultText: '기술 9 · L2 이상 3',
    status: 'SUCCEEDED',
  },
  {
    at: '6월 28일 18:04',
    repositories: 'GitJob',
    resultText: '권한 회수로 중단 · 재연결 후 재시도',
    status: 'FAILED',
  },
]

export const ANALYSIS_HISTORY_NOTE =
  '이력 4건 · 과거 분석은 Snapshot 시점의 Evidence로 고정됩니다. 최신 Level은 최근 분석만 반영합니다.'

/** 계정 · 연결 상태 · 화면 14. 두 계정이 별도로 연결된다는 것이 이 카드의 주제다. */
export const ACCOUNT_CONNECTIONS = {
  displayName: 'dev-user',
  affiliation: 'SSAFY 12기 · 백엔드',
  ssafy: { label: 'SSAFY 계정', detail: '로그인 · 서비스 접근', status: 'SIGNED IN' as const },
  github: {
    label: 'GitHub',
    detail: '@dev-user · 읽기 전용 · Repository 4개 접근',
    status: 'CONNECTED' as const,
  },
  note: 'SSAFY 계정과 GitHub 계정은 별도로 연결됩니다. GitHub 연결을 해제하면 새 분석은 중단되지만 기존 이력은 유지됩니다.',
}

/** 최근 분석 요약 카드 · 화면 14. */
export const LATEST_ANALYSIS_SUMMARY = {
  at: '오늘 10:42',
  status: 'SUCCEEDED' as const,
  repositoryCount: 3,
  techCount: 14,
  personalL2OrAbove: 6,
  snapshotDate: '2026-09-08',
}
