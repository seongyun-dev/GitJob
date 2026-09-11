import type { TargetRoleFixture } from '@/mocks/types'

/**
 * 목표 직무 fixture · 화면 16.
 *
 * 확정 디자인이 이 화면에 `DESIGN MOCK ROLE TAXONOMY` 배지를 직접 달아 두었다.
 * 직무 분류가 아직 제품 결정이라는 뜻이므로, 아래 세 직무도 확정된 목록이 아니다.
 *
 * 이 화면의 요점은 "Evidence는 그대로 두고 비교 집합만 바꾼다"이다. 그래서 직무마다
 * 같은 기술이 다른 표시(`✓` / `△` / `✕`)를 갖는 것이 아니라, **같은 Evidence로
 * 직무마다 충족 결과가 달라지는 것**이 보여야 한다. Apache Kafka가 백엔드에서는
 * 4위 요구인데 데이터 엔지니어에서는 3위인 식이다.
 */
export const TARGET_ROLES: TargetRoleFixture[] = [
  {
    id: 'backend',
    kicker: 'ROLE 01',
    name: '백엔드',
    summary: 'Server · API · Data access',
    jobCount: 87,
    fullMatchCount: 12,
    note: '내 Evidence와 겹치는 필수 기술이 가장 많은 직무입니다.',
    topSkills: [
      { techName: 'Java', requiredCount: 86, mark: 'HAVE', levelText: 'L3' },
      { techName: 'Spring Boot', requiredCount: 74, mark: 'HAVE', levelText: 'L2' },
      { techName: 'MySQL', requiredCount: 52, mark: 'HAVE', levelText: 'L2' },
      { techName: 'Apache Kafka', requiredCount: 31, mark: 'WEAK', levelText: 'L1' },
      { techName: 'AWS', requiredCount: 19, mark: 'NONE', levelText: '없음' },
    ],
  },
  {
    id: 'data',
    kicker: 'ROLE 02',
    name: '데이터 엔지니어',
    summary: 'Pipeline · Warehouse · Streaming',
    jobCount: 34,
    fullMatchCount: 3,
    note: 'Kafka · SQL Evidence는 이어지지만 Python · Spark Evidence가 없습니다.',
    topSkills: [
      { techName: 'Python', requiredCount: 30, mark: 'NONE', levelText: '없음' },
      { techName: 'SQL', requiredCount: 27, mark: 'HAVE', levelText: 'L2' },
      { techName: 'Apache Kafka', requiredCount: 22, mark: 'WEAK', levelText: 'L1' },
      { techName: 'Spark', requiredCount: 19, mark: 'NONE', levelText: '없음' },
      { techName: 'Airflow', requiredCount: 14, mark: 'NONE', levelText: '없음' },
    ],
  },
  {
    id: 'devops',
    kicker: 'ROLE 03',
    name: 'DevOps · 플랫폼',
    summary: 'Infra · CI/CD · Observability',
    jobCount: 29,
    fullMatchCount: 1,
    note: 'Docker · GitHub Actions는 L1까지 확인, 인프라 Evidence는 대부분 없습니다.',
    topSkills: [
      { techName: 'Docker', requiredCount: 26, mark: 'WEAK', levelText: 'L1' },
      { techName: 'Kubernetes', requiredCount: 24, mark: 'NONE', levelText: '없음' },
      { techName: 'AWS', requiredCount: 23, mark: 'NONE', levelText: '없음' },
      { techName: 'Terraform', requiredCount: 17, mark: 'NONE', levelText: '없음' },
      { techName: 'GitHub Actions', requiredCount: 12, mark: 'WEAK', levelText: 'L1' },
    ],
  },
]

/** 화면 16 헤더의 Evidence 요약 문구. */
export const TARGET_ROLE_EVIDENCE_TEXT = '내 Evidence 14개 · 오늘 10:42 분석'
