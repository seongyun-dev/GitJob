/**
 * Landing 미리보기에 쓰는 **연출용 고정값**이다. 티켓 S15P21E102-191.
 *
 * 로그인 전 화면이라 조회할 사용자도 Snapshot도 없다. 그래서 API를 부르지 않고
 * Final 디자인(`GitJob Desktop UI Final.dc.html` · 01 Landing)에 적힌 숫자를 그대로 둔다.
 *
 * **여기서 계산하지 않는다.** 특히 What-if의 `delta`는 C조 분석 결과이지 FE가
 * `after - before`로 만들어도 되는 값이 아니다(PROJECT_GUIDE §2). 세 수치를 각각
 * 상수로 두는 이유가 이것이다. 실제 화면(S4 이후)이 붙으면 이 파일은 지운다.
 */

export const PREVIEW_TITLE = 'Backend match overview'

/** 상단 3분할 지표. `accent`는 하나만 둔다(공용 CountStat의 S4-B 규칙과 같은 이유). */
export const PREVIEW_STATS = [
  { label: '확인된 기술', value: '14', unit: '', caption: 'Personal Evidence 기준', accent: false },
  { label: '전체 공고 매칭', value: '87', unit: '건', caption: '백엔드 공고 전체', accent: false },
  { label: '필수 100% 충족', value: '12', unit: '건', caption: '현재 Evidence 기준', accent: true },
] as const

export const PREVIEW_WHAT_IF = {
  tech: 'Apache Kafka',
  levelPath: 'Personal L1 → 목표 L2',
  rank: '#1 추천',
  beforeLabel: '현재 필수 전체 충족',
  before: '12',
  delta: '+15',
  afterLabel: 'Kafka L2 확보 시',
  after: '27',
} as const

export const PREVIEW_EVIDENCE = {
  icon: 'CFG',
  label: '대표 Evidence',
  location: 'KafkaConfig.java:24',
  usage: '설정 사용',
  level: 'L1',
} as const

/** Hero 하단 요약 문구. */
export const HERO_HIGHLIGHTS = [
  '실제 GitHub Evidence 기반',
  '전체 공고부터 비교',
  'What-if로 다음 기술 확인',
] as const

/**
 * Header 내비게이션 · 목적지는 티켓 212에서 붙였다.
 *
 * 191 시점에는 라벨만 두었다. 근거가 "아직 목적지 화면이 없다"였는데 192·204에서
 * 저장소 선택·공고 매칭·트렌드 라우트가 모두 생겨 조건이 풀렸다.
 *
 * `서비스 소개`만 같은 화면 안의 앵커다. 소개에 해당하는 별도 화면을 만드는 대신
 * 랜딩 아래로 소개 섹션을 이어 붙였다(`ServiceIntro`). Hero의 `서비스 둘러보기`도
 * 같은 곳으로 간다.
 *
 * `GitHub 분석`의 목적지는 결과 화면(`/evidence`)이 아니라 저장소 선택이다. 랜딩에서
 * 오는 사람은 아직 분석한 적이 없어 결과 화면에 보낼 것이 없다. 분석은 저장소를
 * 고르는 데서 시작한다.
 */
export const LANDING_NAV = [
  { label: '서비스 소개', hash: '#service-intro' },
  { label: 'GitHub 분석', to: '/onboarding/repositories' },
  { label: '채용공고 매칭', to: '/jobs' },
  { label: '기술 트렌드', to: '/trends' },
] as const

export type LandingNavItem = (typeof LANDING_NAV)[number]
