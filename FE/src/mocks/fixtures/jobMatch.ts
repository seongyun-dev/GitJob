import type {
  JobMatchScenarioFixture,
  JobPostingFixture,
  JobRequirementFixture,
} from '@/mocks/types'

/**
 * 공고 매칭 fixture · 화면 02.
 *
 * 확정 디자인의 아트보드 02는 필터 상태에 따라 세 얼굴을 갖는다. 셋을 모두 두는
 * 이유는 이 화면에서 깨지기 쉬운 곳이 값이 있을 때가 아니라 **없을 때**여서다.
 * `EMPTY`를 만들어 두지 않으면 우측 Skill Gap 카드가 빈 목록에서 어떻게 되는지
 * 확인하지 못한 채 디자인이 끝난다.
 *
 * 값은 와이어프레임 데모 스크립트의 `ALL` · `MINE` · `EMPTY`를 옮겼다.
 */

/** 표기를 줄이는 생성기. `h`(보유) · `w`(Level 부족) · `x`(Evidence 없음). */
const have = (techName: string): JobRequirementFixture => ({ techName, mark: 'HAVE' })
const weak = (techName: string): JobRequirementFixture => ({ techName, mark: 'WEAK' })
const none = (techName: string): JobRequirementFixture => ({ techName, mark: 'NONE' })

/**
 * 전체 공고 목록.
 *
 * 필수 기술 개수를 3~5개로 흩어 놓은 것이 의도다. 전부 4개면 진행 막대의 칸 수가
 * 항상 같아 실제 화면에서 어떻게 보일지 알 수 없다. 마감(`D-4`~`D-30`)과 지역도
 * 마찬가지로 흩어 두었다.
 */
const POSTINGS: JobPostingFixture[] = [
  {
    id: 'job-nextrail',
    title: '넥스트레일 백엔드 개발자',
    region: '서울',
    career: '신입~3년',
    deadline: 'D-11',
    required: [have('Java'), have('Spring Boot'), have('MySQL'), weak('Apache Kafka')],
    preferred: [have('Docker'), none('AWS'), none('Kubernetes')],
  },
  {
    id: 'job-fintech-settle',
    title: '핀테크 정산 시스템 백엔드',
    region: '서울',
    career: '1~3년',
    deadline: 'D-4',
    // 필수를 전부 충족하는 공고. KPI의 "100% 충족"이 실제로 어떻게 강조되는지 본다.
    required: [have('Java'), have('Spring Boot'), have('MySQL'), have('Redis')],
    preferred: [have('Docker'), have('JPA'), none('AWS')],
  },
  {
    id: 'job-foreground',
    title: '포어그라운드 서버 개발',
    region: '부산',
    career: '신입',
    deadline: 'D-18',
    required: [have('Java'), have('Spring Boot'), have('MySQL')],
    preferred: [have('Redis'), have('Docker'), none('AWS'), none('Kubernetes')],
  },
  {
    id: 'job-commerce',
    title: '커머스 플랫폼 백엔드',
    region: '경기',
    career: '신입~3년',
    deadline: 'D-7',
    required: [
      have('Java'),
      have('Spring Boot'),
      have('Redis'),
      none('AWS'),
      weak('Apache Kafka'),
    ],
    preferred: [have('Docker'), none('Terraform'), none('Kubernetes'), none('Grafana')],
  },
  {
    id: 'job-logistics',
    title: '물류 데이터 API 개발',
    region: '대전',
    career: '신입',
    deadline: 'D-30',
    required: [have('Java'), have('MySQL'), have('Docker'), none('AWS')],
    preferred: [have('Redis'), none('Kubernetes')],
  },
  {
    id: 'job-event-platform',
    title: '이벤트 플랫폼 백엔드 개발',
    region: '서울',
    career: '신입~3년',
    deadline: 'D-21',
    required: [have('Java'), have('Spring Boot'), weak('Apache Kafka'), none('Kubernetes')],
    preferred: [
      have('Docker'),
      have('Redis'),
      none('AWS'),
      none('Grafana'),
      none('Terraform'),
    ],
  },
]

/** 필터를 걸었을 때만 보이는 공고. 전체 목록과 겹치는 건이 있어야 자연스럽다. */
const SEOUL_ENTRY_POSTINGS: JobPostingFixture[] = [
  POSTINGS[0]!,
  {
    id: 'job-healthcare',
    title: '헬스케어 플랫폼 서버 개발',
    region: '서울',
    career: '신입',
    deadline: 'D-9',
    required: [have('Java'), have('Spring Boot'), have('MySQL'), have('Docker')],
    preferred: [have('Redis'), none('AWS'), none('Kubernetes')],
  },
  {
    id: 'job-adtracking',
    title: '광고 트래킹 백엔드',
    region: '서울',
    career: '신입',
    deadline: 'D-15',
    required: [have('Java'), have('Spring Boot'), weak('Apache Kafka')],
    preferred: [have('Redis'), none('AWS'), none('Grafana'), none('Kubernetes')],
  },
  POSTINGS[5]!,
  {
    id: 'job-internal-settle',
    title: '사내 정산 API 개발',
    region: '서울',
    career: '신입',
    deadline: 'D-25',
    required: [have('Java'), have('MySQL'), have('JPA')],
    preferred: [have('Docker'), none('AWS')],
  },
]

/** 필터 없음. 화면 진입 기본 상태다. */
export const JOB_MATCH_ALL: JobMatchScenarioFixture = {
  id: 'ALL',
  headline: '전체 백엔드 공고와 비교했어요',
  kpi: {
    total: 87,
    fullMatch: 12,
    nearMatch: 27,
    lowMatch: 48,
    scopeText: '필터 없음 · 백엔드 전체',
  },
  gapTitle: '전체 공고에서 자주 보이는 Gap',
  gaps: [
    { techName: 'Apache Kafka', requiredCount: 31, levelText: '현재 L1' },
    { techName: 'Kubernetes', requiredCount: 24, levelText: 'Evidence 없음' },
    { techName: 'AWS', requiredCount: 19, levelText: 'Evidence 없음' },
  ],
  moreText: '87개 중 6개 표시 · 스크롤하여 더 보기',
  postings: POSTINGS,
}

/** 지역·경력 필터 적용. KPI 숫자와 Gap 순위가 함께 바뀌는 것이 이 시나리오의 요점이다. */
export const JOB_MATCH_FILTERED: JobMatchScenarioFixture = {
  id: 'FILTERED',
  headline: '서울 · 신입 공고와 비교했어요',
  kpi: {
    total: 32,
    fullMatch: 7,
    nearMatch: 14,
    lowMatch: 11,
    scopeText: '서울 · 신입 적용',
  },
  gapTitle: '서울 · 신입 공고의 Gap',
  gaps: [
    { techName: 'Apache Kafka', requiredCount: 12, levelText: '현재 L1' },
    { techName: 'AWS', requiredCount: 9, levelText: 'Evidence 없음' },
    { techName: 'Kubernetes', requiredCount: 7, levelText: 'Evidence 없음' },
  ],
  moreText: '32개 중 5개 표시 · 스크롤하여 더 보기',
  postings: SEOUL_ENTRY_POSTINGS,
}

/**
 * 결과 0건.
 *
 * 오류가 아니라 조건의 문제라는 것을 화면이 구분해야 한다(화면 15 `EMPTY`).
 * KPI를 0으로 채운 것은 값을 지어낸 게 아니라 "대조한 공고가 0건"이라는 사실이다.
 */
export const JOB_MATCH_EMPTY: JobMatchScenarioFixture = {
  id: 'EMPTY',
  headline: '조건에 맞는 공고가 없어요',
  kpi: { total: 0, fullMatch: 0, nearMatch: 0, lowMatch: 0, scopeText: '부산 · 1~3년 적용' },
  gapTitle: '비교할 공고가 없어요',
  gaps: [],
  moreText: '',
  postings: [],
}

export const JOB_MATCH_SCENARIOS: JobMatchScenarioFixture[] = [
  JOB_MATCH_ALL,
  JOB_MATCH_FILTERED,
  JOB_MATCH_EMPTY,
]

/** 필터 선택지. 와이어프레임의 select 옵션 그대로다. */
export const JOB_FILTER_OPTIONS = {
  regions: ['지역 전체', '서울', '경기', '부산', '대전'],
  careers: ['경력 전체', '신입', '신입~3년', '1~3년'],
} as const

/** 화면 02 헤더의 공고 Snapshot 표기. 분석 시각과 다른 값이다. */
export const JOB_SNAPSHOT_TEXT = '2026-09-08 수집 · 백엔드'
