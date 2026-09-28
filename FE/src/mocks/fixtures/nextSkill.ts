import type { JobRequirementFixture, NextSkillFixture } from '@/mocks/types'

/**
 * 다음 학습 기술 · What-if fixture · 화면 10·03.
 *
 * 두 화면이 같은 데이터를 다르게 보여준다. 10은 세 후보를 나열하고, 03은 하나를 골라
 * 새로 충족되는 공고를 펼친다. 그래서 fixture도 하나만 둔다 — 따로 두면 두 화면의
 * 숫자가 어긋난다.
 *
 * **정렬 기준이 "필수 전체 충족 공고 증가 수" 하나뿐인 것이 이 화면의 규칙이다.**
 * 추천 점수를 만들지 않으므로 `score` 같은 필드를 두지 않았다. 순서를 바꾸고 싶으면
 * `projectedFullMatch - currentFullMatch`를 바꿔야 한다.
 *
 * `currentFullMatch`는 셋 다 12로 같다. 같은 비교 집합(백엔드 87건)의 현재 상태라
 * 기술마다 다를 수 없기 때문이다.
 */

const have = (techName: string): JobRequirementFixture => ({ techName, mark: 'HAVE' })
const weak = (techName: string): JobRequirementFixture => ({ techName, mark: 'WEAK' })
const none = (techName: string): JobRequirementFixture => ({ techName, mark: 'NONE' })

export const NEXT_SKILLS: NextSkillFixture[] = [
  {
    techId: 'kafka',
    rank: '#1',
    techName: 'Apache Kafka',
    shortName: 'Kafka',
    fromLevel: 'L1',
    targetLevel: 'L2',
    currentFullMatch: 12,
    projectedFullMatch: 27,
    headline: 'Kafka를 L2로 만들면 무엇이 달라질까요?',
    ctaLabel: 'Kafka 추천 기술 상세 보기',
    reasons: [
      '현재 비교 중인 백엔드 공고에서 가장 많이 요구되는 미충족 기술',
      'Java L3 · Spring Boot L2 선행 기술을 이미 충족',
      'Producer 또는 Consumer 구현으로 L2 Evidence 목표가 명확',
    ],
    newlyMatched: [
      {
        title: '이벤트 플랫폼 백엔드',
        meta: '서울 · 신입~3년',
        chips: [have('Java'), have('Spring Boot'), weak('Apache Kafka')],
        why: '현재 Kafka 미충족 → Kafka L2 가정 시 필수 기술 전체 충족',
      },
      {
        title: '실시간 데이터 서버 개발',
        meta: '부산 · 신입',
        chips: [have('Java'), have('Redis'), weak('Apache Kafka')],
        why: '새롭게 충족되는 기술 · Apache Kafka',
      },
      {
        title: '커머스 메시징 플랫폼',
        meta: '경기 · 1~3년',
        chips: [have('Spring Boot'), have('MySQL'), weak('Apache Kafka')],
        why: '필수 2/3 → What-if 3/3',
      },
      {
        title: '주문 이벤트 처리 서버',
        meta: '서울 · 신입',
        chips: [have('Java'), have('Docker'), weak('Apache Kafka')],
        why: '필수 75% → What-if 100%',
      },
    ],
  },
  {
    // Evidence가 아예 없는 기술. `fromLevel` L0의 배지가 L1·L2와 다르게 보여야 한다.
    techId: 'aws',
    rank: '#2',
    techName: 'AWS',
    shortName: 'AWS',
    fromLevel: 'L0',
    targetLevel: 'L2',
    currentFullMatch: 12,
    projectedFullMatch: 23,
    headline: 'AWS를 L2로 만들면 무엇이 달라질까요?',
    ctaLabel: 'AWS 추천 기술 상세 보기',
    reasons: [
      '필수 요구 19건 중 현재 Evidence가 전혀 없는 기술',
      'Docker Evidence가 있어 배포 맥락의 선행 조건은 충족',
      'EC2 · S3 설정 파일과 배포 스크립트로 Evidence 확보 가능',
    ],
    newlyMatched: [
      {
        title: '물류 데이터 API 개발',
        meta: '대전 · 신입',
        chips: [have('Java'), have('MySQL'), none('AWS')],
        why: '현재 AWS 미충족 → AWS L2 가정 시 필수 기술 전체 충족',
      },
      {
        title: '클라우드 정산 백엔드',
        meta: '서울 · 신입~3년',
        chips: [have('Java'), have('Spring Boot'), none('AWS')],
        why: '필수 2/3 → What-if 3/3',
      },
      {
        title: 'SaaS 백오피스 서버',
        meta: '경기 · 신입',
        chips: [have('Spring Boot'), have('MySQL'), none('AWS')],
        why: '새롭게 충족되는 기술 · AWS',
      },
      {
        title: '미디어 스트리밍 API',
        meta: '서울 · 1~3년',
        chips: [have('Java'), have('Redis'), none('AWS')],
        why: '필수 66% → What-if 100%',
      },
    ],
  },
  {
    techId: 'docker',
    rank: '#3',
    techName: 'Docker',
    shortName: 'Docker',
    fromLevel: 'L1',
    targetLevel: 'L2',
    currentFullMatch: 12,
    projectedFullMatch: 20,
    headline: 'Docker를 L2로 만들면 무엇이 달라질까요?',
    ctaLabel: 'Docker 추천 기술 상세 보기',
    reasons: [
      'Personal L1 Evidence가 이미 있어 목표까지 거리가 가장 짧음',
      '필수 요구 16건 · 우대 요구 22건으로 활용 범위가 넓음',
      'Multi-stage build와 Compose 구성으로 L2 Evidence 확보 가능',
    ],
    newlyMatched: [
      {
        title: '인프라 자동화 백엔드',
        meta: '서울 · 신입~3년',
        chips: [have('Java'), have('Spring Boot'), weak('Docker')],
        why: '현재 Docker L1 → L2 가정 시 필수 기술 전체 충족',
      },
      {
        title: '헬스케어 API 서버',
        meta: '서울 · 신입',
        chips: [have('Java'), have('MySQL'), weak('Docker')],
        why: '필수 2/3 → What-if 3/3',
      },
      {
        title: '사내 배포 플랫폼 개발',
        meta: '경기 · 1~3년',
        chips: [have('Spring Boot'), have('Redis'), weak('Docker')],
        why: '새롭게 충족되는 기술 · Docker',
      },
      {
        title: '게임 정산 서버',
        meta: '부산 · 신입',
        chips: [have('Java'), have('JPA'), weak('Docker')],
        why: '필수 75% → What-if 100%',
      },
    ],
  },
]

/**
 * 화면 03·10이 함께 쓰는 경고 문구.
 *
 * 이 화면에서 가장 오해받기 쉬운 것이 "공고 수 변화"라 문구를 fixture에 함께 둔다.
 * 화면마다 다르게 쓰면 같은 수치에 다른 해석이 붙는다.
 */
export const WHAT_IF_DISCLAIMER =
  '공고 수 변화는 합격 가능성이 아니라, 해당 기술의 Personal Evidence를 목표 Level로 확보했다고 가정했을 때 필수 기술요건을 모두 충족하는 공고 수입니다. 가이드의 Task를 완료해도 Level은 자동으로 오르지 않으며 GitHub 재분석으로만 갱신됩니다.'
