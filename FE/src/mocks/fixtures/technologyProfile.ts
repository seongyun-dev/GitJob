import type { TechnologyProfile } from '@/features/evidence/api/types'

/**
 * `GET /me/profile` 응답 fixture · 화면 08 My Evidence.
 *
 * **타입을 느슨하게 두지 않았다.** 이 화면만 계약이 이미 고정돼 있어
 * (`features/evidence/api/types.ts`, 티켓 208) fixture도 그 타입을 그대로 만족한다.
 * 그래야 나중에 BE 응답으로 갈아끼울 때 화면을 고치지 않는다. 타입이 안 맞으면
 * fixture를 느슨하게 만들 게 아니라 계약 이해가 틀린 것이다.
 *
 * 값은 확정 디자인 `GitJob_FE_Final_v2_17screens.html`의 아트보드 08에서 옮겼다.
 * 기술 14개 · Personal L2 이상 6개 · 근거 보강 필요 3개 · L0 3개가 그 화면의
 * 상단 KPI와 맞아떨어져야 하므로 개수를 바꾸려면 네 값을 함께 바꾼다.
 *
 * 계약에 없는 표시값(대표 파일 경로, "본인 Commit 218" 같은 문구)은 여기 없다.
 * `evidenceScreen.ts`가 따로 갖는다 — 어디까지가 계약이고 어디부터가 화면 문구인지
 * 섞이면 나중에 BE가 안 주는 값을 화면이 기대하게 된다.
 */

/** 분석 시각. 화면의 "오늘 10:42"는 KST 표기이고 계약은 UTC ISO-8601이다. */
const ANALYZED_AT = '2026-09-11T01:42:00Z'

const CRITERIA: TechnologyProfile['criteria'] = {
  registryVersion: 'registry-20260908.1',
  registryChecksum: 'sha256:4f1c8d5b9a2e7c3648d0b1f7a9c25e83d6047b1ea3c94d20',
  repositoryCount: 3,
  analyzedRepositoryCount: 3,
  commitShas: [
    { repoFullName: 'dev-user/GitJob', commitSha: '3f9a2c1d84b7e0526a1c9f3d70b8e4152c6a9d38' },
    { repoFullName: 'dev-user/RO-KI', commitSha: 'c04b77e21f5a8d6390be4c17d25f80a9e3b61c47' },
    { repoFullName: 'dev-user/algo-study', commitSha: '9b13d5f70c28a4e615d9c037b8e2a4f61d05c9ba' },
  ],
  limits: { maxRepositories: 5, maxFilesPerRepository: 1500 },
}

/**
 * 판정 방식의 한계. 명세가 이 배열을 두는 이유는 수치를 그대로 믿지 않게 하려는
 * 것이므로, fixture에서도 빈 배열로 두지 않는다 — 빈 배열이면 화면이 이 영역을
 * 렌더하지 않아 레이아웃을 확인할 수 없다.
 */
const JUDGEMENT_LIMITS = [
  'Level은 Evidence 유형으로만 판정합니다. 숙련도나 코드 품질을 평가하지 않습니다.',
  'Personal Level은 본인 Commit으로 확인된 범위입니다. 타인 Commit의 구현은 Repository Level에만 반영됩니다.',
  '의존성 선언만 확인된 기술은 사용 여부를 판정하지 않습니다.',
]

export const TECHNOLOGY_PROFILE: TechnologyProfile = {
  analysisId: 'anl-20260911-0142',
  analyzedAt: ANALYZED_AT,
  partial: false,
  missingScope: [],
  criteria: CRITERIA,
  judgementLimits: JUDGEMENT_LIMITS,
  categories: [
    {
      categoryCode: 'BACKEND',
      categoryName: '백엔드',
      technologies: [
        {
          techId: 'java',
          techName: 'Java',
          repoLevel: 'L3',
          personalLevel: 'L3',
          evidenceCount: 218,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-09-08T12:31:00Z',
        },
        {
          techId: 'spring-boot',
          techName: 'Spring Boot',
          repoLevel: 'L3',
          personalLevel: 'L2',
          evidenceCount: 64,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-09-05T08:12:00Z',
        },
        {
          techId: 'jpa',
          techName: 'JPA',
          repoLevel: 'L2',
          personalLevel: 'L2',
          evidenceCount: 41,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-08-29T05:44:00Z',
        },
        {
          techId: 'spring-security',
          techName: 'Spring Security',
          repoLevel: 'L2',
          personalLevel: 'L2',
          evidenceCount: 12,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-08-21T11:05:00Z',
        },
        {
          // 화면 09·10·11·13이 모두 이 기술을 예시로 쓴다. Repository L2 · Personal L1의
          // 차이가 그 화면들의 주제라 두 Level을 다르게 두는 것이 중요하다.
          techId: 'kafka',
          techName: 'Apache Kafka',
          repoLevel: 'L2',
          personalLevel: 'L1',
          evidenceCount: 3,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-08-02T09:18:00Z',
        },
      ],
    },
    {
      categoryCode: 'DATABASE',
      categoryName: '데이터베이스',
      technologies: [
        {
          techId: 'mysql',
          techName: 'MySQL',
          repoLevel: 'L2',
          personalLevel: 'L2',
          evidenceCount: 37,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-09-04T02:20:00Z',
        },
        {
          techId: 'redis',
          techName: 'Redis',
          repoLevel: 'L2',
          personalLevel: 'L2',
          evidenceCount: 19,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-08-27T14:03:00Z',
        },
        {
          techId: 'elasticsearch',
          techName: 'Elasticsearch',
          repoLevel: 'L0',
          personalLevel: 'L0',
          evidenceCount: 1,
          representativeRepo: 'dev-user/RO-KI',
          lastUsedAt: '2026-06-19T07:41:00Z',
        },
        {
          techId: 'flyway',
          techName: 'Flyway',
          repoLevel: 'L0',
          personalLevel: 'L0',
          evidenceCount: 1,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-05-30T10:26:00Z',
        },
      ],
    },
    {
      categoryCode: 'INFRASTRUCTURE',
      categoryName: '인프라',
      technologies: [
        {
          techId: 'docker',
          techName: 'Docker',
          repoLevel: 'L2',
          personalLevel: 'L1',
          evidenceCount: 8,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-08-18T16:52:00Z',
        },
        {
          techId: 'github-actions',
          techName: 'GitHub Actions',
          repoLevel: 'L1',
          personalLevel: 'L1',
          evidenceCount: 4,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-08-11T03:37:00Z',
        },
        {
          techId: 'gradle',
          techName: 'Gradle',
          repoLevel: 'L1',
          personalLevel: 'L1',
          evidenceCount: 6,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-09-08T12:31:00Z',
        },
      ],
    },
    {
      categoryCode: 'TESTING',
      categoryName: '테스트',
      technologies: [
        {
          techId: 'junit',
          techName: 'JUnit',
          repoLevel: 'L1',
          personalLevel: 'L1',
          evidenceCount: 3,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-07-24T13:09:00Z',
        },
      ],
    },
    {
      // 빈 카테고리를 일부러 남긴다. 명세 예시의 `OTHER`가 빈 배열이고, 화면이 이
      // 경우에 헤더만 덩그러니 렌더하지 않는지 디자인 단계에서 봐야 한다.
      categoryCode: 'OBSERVABILITY',
      categoryName: '관측',
      technologies: [],
    },
    {
      categoryCode: 'OTHER',
      categoryName: '기타',
      technologies: [
        {
          techId: 'lombok',
          techName: 'Lombok',
          repoLevel: 'L0',
          personalLevel: 'L0',
          evidenceCount: 1,
          representativeRepo: 'dev-user/GitJob',
          lastUsedAt: '2026-09-08T12:31:00Z',
        },
      ],
    },
  ],
}

/**
 * 부분 결과 변형 · 화면 15 `PARTIAL`.
 *
 * 완전한 결과만 두면 `partial` 배너와 `missingScope` 문장이 들어갈 자리를 디자인할 수
 * 없다. 명세가 이 둘을 같은 응답에 싣는 이유가 "일부 실패를 감추면 사용자가 전체를 본
 * 것으로 오해한다"이므로, 그 문장이 실제로 어디에 놓이는지 확인할 fixture가 필요하다.
 *
 * 목록을 줄이지 않고 플래그만 바꾼 것이 아니라 저장소 하나 분량(RO-KI의 기술)을
 * 실제로 뺐다. 개수가 그대로면 "부분인데 다 보인다"는 잘못된 화면이 된다.
 */
export const PARTIAL_TECHNOLOGY_PROFILE: TechnologyProfile = {
  ...TECHNOLOGY_PROFILE,
  analysisId: 'anl-20260803-2110',
  analyzedAt: '2026-08-03T12:10:00Z',
  partial: true,
  missingScope: ['RO-KI 저장소는 GitHub 호출 한도(RATE_LIMITED)로 분석이 중단되었습니다.'],
  criteria: { ...CRITERIA, repositoryCount: 2, analyzedRepositoryCount: 1 },
  categories: TECHNOLOGY_PROFILE.categories.map((category) => ({
    ...category,
    technologies: category.technologies.filter((tech) => tech.representativeRepo !== 'dev-user/RO-KI'),
  })),
}
