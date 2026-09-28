import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * 화면 08·09가 쓰지만 계약에는 없는 표시값.
 *
 * **이 파일이 따로 있는 이유가 중요하다.** 확정 디자인의 My Evidence 표에는
 * `대표 EVIDENCE` 열이 있고 `Main.java` / `외 42개 파일 · 본인 Commit 218` 같은
 * 문구가 들어간다. 그런데 `GET /me/profile` 계약(B-FN-010)이 주는 것은
 * `representativeRepo`와 `evidenceCount`뿐이다 — 대표 **파일**도, 그 설명 문구도 없다.
 *
 * 그 차이를 fixture에서 지워 버리면 화면을 다 만든 뒤에야 "이 열은 채울 수 없다"는
 * 것을 알게 된다. 그래서 계약 fixture(`technologyProfile.ts`)와 섞지 않고 여기 둔다.
 * 이 파일에 있는 값은 전부 **BE에 요청해야 하거나 화면에서 빼야 하는 후보**다.
 */

/** 대표 Evidence 열 한 칸. 계약에 대응 필드가 없다. */
export interface RepresentativeEvidenceFixture {
  techId: string
  /** 대표 파일 경로. 계약 미제공 — BE 협의 필요. */
  filePath: string
  /** 그 아래 회색 보조 문구. 계약 미제공. */
  caption: string
  /** Repository Level이 Personal보다 높을 때 붙는 경고 문구. 없으면 null. */
  gapNote: string | null
}

export const REPRESENTATIVE_EVIDENCE: RepresentativeEvidenceFixture[] = [
  {
    techId: 'java',
    filePath: 'Main.java',
    caption: '외 42개 파일 · 본인 Commit 218',
    gapNote: null,
  },
  {
    techId: 'spring-boot',
    filePath: 'Application.java',
    caption: 'Bean 구성 · 본인 Commit 64',
    gapNote: 'Repository L3 · 본인 Commit 근거 부족',
  },
  {
    techId: 'mysql',
    filePath: 'application.yml',
    caption: 'datasource 설정 · Repository 구현',
    gapNote: null,
  },
  { techId: 'redis', filePath: 'RedisConfig.java:18', caption: '캐시 구현', gapNote: null },
  { techId: 'jpa', filePath: 'OrderRepository.java', caption: '쿼리 메서드 구현', gapNote: null },
  {
    techId: 'spring-security',
    filePath: 'SecurityConfig.java:31',
    caption: '필터 체인 구성',
    gapNote: null,
  },
  {
    techId: 'kafka',
    filePath: 'KafkaConfig.java:24',
    caption: '설정 사용 · Consumer 구현은 타인 Commit',
    gapNote: 'Repository L2 · 본인 Commit 근거 부족',
  },
  {
    techId: 'docker',
    filePath: 'Dockerfile',
    caption: '단일 스테이지 빌드',
    gapNote: 'Repository L2 · 본인 Commit 근거 부족',
  },
  { techId: 'gradle', filePath: 'build.gradle', caption: '의존성 관리', gapNote: null },
  { techId: 'junit', filePath: 'OrderServiceTest.java', caption: '단위 테스트 3개', gapNote: null },
  {
    techId: 'github-actions',
    filePath: '.github/workflows/ci.yml',
    caption: '빌드 워크플로우',
    gapNote: null,
  },
  {
    techId: 'elasticsearch',
    filePath: 'build.gradle',
    caption: '의존성 선언만',
    gapNote: null,
  },
  { techId: 'flyway', filePath: 'build.gradle', caption: '의존성 선언만', gapNote: null },
  {
    techId: 'lombok',
    filePath: 'build.gradle',
    caption: '어노테이션 프로세서 선언',
    gapNote: null,
  },
]

/**
 * 화면 08 상단 KPI 4칸.
 *
 * 값을 하드코딩하지 않고 프로필 fixture에서 세어 쓰는 편이 안전하지만, 세는 규칙
 * 자체가 아직 제품 정의다("근거 보강 필요"의 기준이 Repository > Personal인지,
 * 몇 단계 차이부터인지). 규칙이 정해지기 전까지 디자인이 참조할 값만 둔다.
 */
export const EVIDENCE_SUMMARY = {
  confirmedTechCount: 14,
  personalL2OrAbove: 6,
  needsMoreEvidence: 3,
  declarationOnly: 3,
} as const

/** 화면 08 우측 "근거 보강 필요" 카드. */
export interface ReinforcementFixture {
  techId: string
  techName: string
  reason: string
  personalLevel: EvidenceLevel
  repoLevel: EvidenceLevel
}

export const REINFORCEMENT_NEEDED: ReinforcementFixture[] = [
  {
    techId: 'spring-boot',
    techName: 'Spring Boot',
    reason: 'Bean 구성 외 심화 구현이 타인 Commit',
    personalLevel: 'L2',
    repoLevel: 'L3',
  },
  {
    techId: 'kafka',
    techName: 'Apache Kafka',
    reason: 'Consumer 구현이 타인 Commit',
    personalLevel: 'L1',
    repoLevel: 'L2',
  },
  {
    techId: 'docker',
    techName: 'Docker',
    reason: 'Compose 구성이 타인 Commit',
    personalLevel: 'L1',
    repoLevel: 'L2',
  },
]

/** 화면 08·09 우측 `ANALYSIS CONTEXT` 카드의 저장소 한 줄. */
export interface AnalysisContextRepoFixture {
  name: string
  languages: string
  /** 이 저장소에서 확인된 기술 수. */
  techCount: number
  /** 본인 Commit 비율 표기. */
  ownCommitText: string
}

export const ANALYSIS_CONTEXT_REPOS: AnalysisContextRepoFixture[] = [
  { name: 'GitJob', languages: 'Java · Spring Boot', techCount: 11, ownCommitText: '본인 Commit 62%' },
  { name: 'RO-KI', languages: 'Java · Python', techCount: 7, ownCommitText: '본인 Commit 38%' },
  { name: 'algo-study', languages: 'Java', techCount: 2, ownCommitText: '본인 Commit 100%' },
]

/** 화면 08·09 헤더의 분석 시각 문구. Snapshot 날짜는 공고 수집일이라 별개 값이다. */
export const ANALYSIS_CONTEXT_FOOTER = '오늘 10:42 · SUCCEEDED · Snapshot 2026-09-08'

/**
 * 화면 09 우측 "L2가 되려면?" 사다리.
 *
 * 계약의 `unmetRules`·`nextActions`가 같은 내용을 다른 모양으로 준다. 어느 쪽으로
 * 화면을 만들지 정하기 전이라 디자인용 형태를 따로 둔다 — 정해지면 이 배열은 지우고
 * `KAFKA_EVIDENCE.nextActions`를 쓴다.
 */
export interface LevelLadderStepFixture {
  level: EvidenceLevel
  title: string
  detail: string
  /** 충족 `DONE` · 진행 필요 `TODO` · 아직 먼 단계 `LOCKED`. */
  state: 'DONE' | 'TODO' | 'LOCKED'
}

export const KAFKA_LEVEL_LADDER: LevelLadderStepFixture[] = [
  { level: 'L0', title: '의존성 선언', detail: 'build.gradle', state: 'DONE' },
  { level: 'L1', title: '설정 사용', detail: 'KafkaConfig.java:24', state: 'DONE' },
  { level: 'L2', title: 'Producer / Consumer 구현', detail: '본인 Commit 필요', state: 'TODO' },
  { level: 'L3', title: '반복 구현 + 다수 Commit', detail: '—', state: 'LOCKED' },
]
