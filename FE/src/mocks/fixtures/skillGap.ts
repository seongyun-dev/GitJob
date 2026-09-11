import type { SkillGapGroupFixture, SkillGapSummaryFixture } from '@/mocks/types'

/**
 * Skill Gap 상세 fixture · 화면 17.
 *
 * 이 화면의 주제는 "점수가 아니라 기술별 충족 · 부족 · 판단 근거 부족 구분"이다.
 * 그래서 표를 판정별로 네 묶음으로 나눈다. 묶음을 하나로 합치고 배지로만 구분하면
 * 그 주제가 사라진다.
 *
 * **`UNDETERMINED`(판단 근거 부족)를 부족으로 세지 않는 것이 규칙이다.** 요구 기술
 * 19종 = 충족 8 + 부족 9 + 미판정 2이고, `gapCount`는 9다. 숫자를 바꿀 때 이
 * 관계가 깨지면 화면이 스스로 모순된다.
 *
 * `fillDelta`("채우면 +N")는 그 기술 **하나만** 채웠을 때의 변화라 행끼리 더할 수
 * 없다. 합계 칸을 만들지 않는 것이 이 값의 전제다.
 */

export const SKILL_GAP_SUMMARY: SkillGapSummaryFixture = {
  basisText: '백엔드 · 전체 공고 87건',
  requiredTechCount: 19,
  metCount: 8,
  gapCount: 9,
  gapBreakdown: 'Evidence 없음 6 · Level 부족 3',
  undeterminedCount: 2,
}

export const SKILL_GAP_GROUPS: SkillGapGroupFixture[] = [
  {
    verdict: 'NO_EVIDENCE',
    title: 'EVIDENCE 없음',
    description: 'GitHub에서 선언 · 설정 · 구현 어느 것도 확인되지 않음',
    rows: [
      {
        techName: 'Kubernetes',
        requiredCount: 24,
        preferredCount: 18,
        personalLevel: null,
        verdict: 'NO_EVIDENCE',
        verdictText: '미보유',
        fillDelta: 6,
      },
      {
        techName: 'AWS',
        requiredCount: 19,
        preferredCount: 25,
        personalLevel: null,
        verdict: 'NO_EVIDENCE',
        verdictText: '미보유',
        fillDelta: 11,
      },
      {
        techName: 'Terraform',
        requiredCount: 4,
        preferredCount: 12,
        personalLevel: null,
        verdict: 'NO_EVIDENCE',
        verdictText: '미보유',
        fillDelta: 1,
      },
      {
        // 채워도 늘어나는 공고가 없는 행. 0과 null을 구분해야 하는 자리라 일부러 남긴다.
        techName: 'Grafana',
        requiredCount: 3,
        preferredCount: 10,
        personalLevel: null,
        verdict: 'NO_EVIDENCE',
        verdictText: '미보유',
        fillDelta: 0,
      },
      {
        techName: 'MongoDB',
        requiredCount: 5,
        preferredCount: 7,
        personalLevel: null,
        verdict: 'NO_EVIDENCE',
        verdictText: '미보유',
        fillDelta: 2,
      },
      {
        techName: 'Python',
        requiredCount: 6,
        preferredCount: 9,
        personalLevel: null,
        verdict: 'NO_EVIDENCE',
        verdictText: '미보유',
        fillDelta: 2,
      },
    ],
  },
  {
    verdict: 'LEVEL_SHORT',
    title: 'LEVEL 부족',
    description: 'Evidence는 있지만 공고가 요구하는 구현(L2) Level에 미달',
    rows: [
      {
        techName: 'Apache Kafka',
        requiredCount: 31,
        preferredCount: 12,
        personalLevel: 'L1',
        verdict: 'LEVEL_SHORT',
        verdictText: 'L2 요구',
        fillDelta: 15,
      },
      {
        techName: 'Docker',
        requiredCount: 16,
        preferredCount: 22,
        personalLevel: 'L1',
        verdict: 'LEVEL_SHORT',
        verdictText: 'L2 요구',
        fillDelta: 8,
      },
      {
        techName: 'GitHub Actions',
        requiredCount: 2,
        preferredCount: 9,
        personalLevel: 'L1',
        verdict: 'LEVEL_SHORT',
        verdictText: 'L2 요구',
        fillDelta: 1,
      },
    ],
  },
  {
    verdict: 'UNDETERMINED',
    title: '판단 근거 부족',
    description: '의존성 선언만 있어 사용 여부를 판정하지 않음 · Gap으로 세지 않음',
    rows: [
      {
        techName: 'Elasticsearch',
        requiredCount: 7,
        preferredCount: 11,
        personalLevel: 'L0',
        verdict: 'UNDETERMINED',
        verdictText: '미판정',
        // 판정하지 않은 기술의 변화량은 계산하지 않는다. 0이 아니라 null이다.
        fillDelta: null,
      },
      {
        techName: 'Flyway',
        requiredCount: 1,
        preferredCount: 6,
        personalLevel: 'L0',
        verdict: 'UNDETERMINED',
        verdictText: '미판정',
        fillDelta: null,
      },
    ],
  },
  {
    verdict: 'MET',
    title: '충족',
    description: '요구 Level 이상의 Personal Evidence 보유',
    rows: [
      {
        techName: 'Java',
        requiredCount: 86,
        // 우대 요구가 아예 없는 행. 0건과 구분하려고 null을 쓴다.
        preferredCount: null,
        personalLevel: 'L3',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
      {
        techName: 'Spring Boot',
        requiredCount: 74,
        preferredCount: 6,
        personalLevel: 'L2',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
      {
        techName: 'MySQL',
        requiredCount: 52,
        preferredCount: 14,
        personalLevel: 'L2',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
      {
        techName: 'JPA',
        requiredCount: 30,
        preferredCount: 18,
        personalLevel: 'L2',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
      {
        techName: 'Redis',
        requiredCount: 28,
        preferredCount: 21,
        personalLevel: 'L2',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
      {
        techName: 'Spring Security',
        requiredCount: 12,
        preferredCount: 15,
        personalLevel: 'L2',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
      {
        techName: 'JUnit',
        requiredCount: 9,
        preferredCount: 20,
        personalLevel: 'L1',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
      {
        techName: 'Gradle',
        requiredCount: 3,
        preferredCount: 9,
        personalLevel: 'L1',
        verdict: 'MET',
        verdictText: '충족',
        fillDelta: null,
      },
    ],
  },
]

/** 화면 17 하단 판정 기준 범례. 표기 규칙을 화면마다 다시 쓰지 않도록 여기 둔다. */
export const SKILL_GAP_LEGEND = [
  { mark: '✓', label: '충족', detail: '요구 Level 이상 Personal Evidence' },
  { mark: '△', label: 'Level 부족', detail: 'Evidence 있음 · 요구 L2 미달' },
  { mark: '✕', label: 'Evidence 없음', detail: '선언 · 설정 · 구현 모두 없음' },
  { mark: '?', label: '판단 근거 부족', detail: '선언만 · Gap으로 세지 않음' },
] as const

export const SKILL_GAP_FOOTNOTE =
  '"채우면 +N"은 그 기술 하나만 요구 Level로 확보했다고 가정했을 때 필수 전체 충족 공고가 몇 건 늘어나는지입니다. 합계 · 점수로 환산하지 않습니다.'
