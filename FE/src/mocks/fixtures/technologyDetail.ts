import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * 추천 기술 상세 fixture · 화면 11.
 *
 * 이 화면은 탭 넷(추천 근거 · 프로젝트 · FAQ/Pain · Trend)으로 나뉘고 탭마다 성격이
 * 다른 데이터를 쓴다. 현재 페이지(`TechnologyDetailPage`)가 탭을 만들지 않은 이유는
 * "전환할 데이터가 없어서"였다 — 이 fixture가 그 데이터다.
 *
 * 출처는 확정 디자인 아트보드 11이고 기술은 Apache Kafka 하나다. 화면 구조를 잡는 데
 * 하나면 충분하고, 여러 기술을 두면 어느 값이 실제 계약이 될지 판단하기 더 어려워진다.
 */

/** 01 현재 상태 · 지금 확인된 Level과 그 근거. */
export const CURRENT_STATE = {
  personalLevel: 'L1' as EvidenceLevel,
  repoLevel: 'L2' as EvidenceLevel,
  summary: 'Personal L1 · 설정 사용까지 확인',
  evidenceFile: 'KafkaConfig.java:24',
  evidenceCaption: 'ProducerFactory Bean · 본인 Commit',
  gapReason:
    'RO-KI에 Consumer 구현이 있지만 타인 Commit이라 Repository L2 · Personal L1입니다.',
}

/**
 * 02 왜 필요한가 · 공고 수요와 선행 기술.
 *
 * `counterSignal`이 이 섹션의 핵심이다. 수요가 높다는 신호만 보여주면 화면이 한쪽
 * 근거만 제시하게 된다. 다른 출처가 반대 방향일 때 그 사실을 같이 적는 자리다.
 */
export const WHY_NEEDED = {
  requiredCount: 31,
  totalJobCount: 87,
  rankNote: '미충족 기술 중 1위',
  prerequisiteText: 'Java L3 · Spring Boot L2',
  prerequisiteMet: true,
  whatIfText: '필수 전체 충족 12 → 27',
  whatIfDelta: 15,
  counterSignal:
    'GitHub Trend는 언어 단위만 지원해 Kafka는 NOT_SUPPORTED입니다. 채용 수요와 별개로 참고만 하세요.',
}

/** 03 어떤 Evidence가 필요한가 · L2 판정 기준. */
export const LEVEL_CRITERIA = [
  {
    no: 1,
    title: 'Producer 또는 Consumer 구현',
    detail: 'KafkaTemplate 전송 또는 @KafkaListener 소비 로직이 코드에 존재',
  },
  {
    no: 2,
    title: '본인 Commit',
    detail: '해당 구현 파일의 Commit 작성자가 본인으로 확인',
  },
]

export const LEVEL_CRITERIA_NOTE =
  '판정 기준은 학습 체크리스트가 아닙니다. 조건을 만족하는 코드를 Push하고 GitHub를 다시 분석해야 Level이 바뀝니다.'

/** 04 무엇을 만들어보면 되나 · 프로젝트 가이드 탭. */
export const PROJECT_GUIDE = {
  title: '주문 이벤트 기반 재고 · 알림 처리 시스템',
  difficulty: 'INTERMEDIATE',
  duration: '약 2주',
  summary:
    '주문 생성 이벤트를 Kafka로 발행하고, 재고 차감과 알림 발송을 별도 Consumer Group으로 분리해 처리합니다. 기존 Spring Boot · MySQL Evidence 위에 Kafka L2 Evidence를 쌓는 구성입니다.',
  tasks: [
    {
      no: '01',
      title: '주문 이벤트 Producer',
      detail: 'OrderCreated 이벤트를 KafkaTemplate으로 발행 · 직렬화 설정',
    },
    {
      no: '02',
      title: 'Consumer Group 분리',
      detail: '재고 Consumer와 알림 Consumer를 서로 다른 group.id로 구성',
    },
    {
      no: '03',
      title: '멱등 처리',
      detail: '이벤트 중복 소비 시 재고가 두 번 차감되지 않도록 처리 키 저장',
    },
    {
      no: '04',
      title: 'Retry / DLQ',
      detail: '실패 이벤트 재시도 정책과 Dead Letter Topic 구성',
    },
  ],
  evidenceGoals: ['Producer / Consumer 구현', 'Consumer Group 설정', '해당 구현의 본인 기여 Commit'],
  warning:
    'Evidence는 자동으로 올라가지 않습니다. Task를 완료해도 Level이 바뀌지 않으며, 구현을 GitHub에 Push한 뒤 재분석해야 Personal L2로 판정됩니다.',
}

/**
 * FAQ / Pain Point 탭.
 *
 * `relatedQuestionCount`의 출처가 Stack Overflow인데, 그 출처는 현재 수집 입력에
 * 없다(`docs/ai/c-public-trend.md` 10행). 이 탭 전체가 출처 확보에 달려 있다는
 * 뜻이므로, 화면을 만들 때 값이 없는 경우를 함께 설계해야 한다.
 */
export const FAQ_ITEMS = [
  {
    no: '01',
    topic: 'Consumer Group 설정',
    question: '같은 group.id의 Consumer가 파티션을 나눠 받지 않고 중복 소비되는 이유는?',
    relatedQuestionCount: 1240,
  },
  {
    no: '02',
    topic: 'Offset 관리',
    question: 'auto.offset.reset = earliest / latest 차이와 재처리 시 Offset을 되돌리는 방법',
    relatedQuestionCount: 980,
  },
  {
    no: '03',
    topic: 'Broker 연결',
    question: 'Docker 컨테이너 안의 Kafka에 로컬 애플리케이션이 연결되지 않는 문제',
    relatedQuestionCount: 870,
  },
  {
    no: '04',
    topic: 'advertised.listeners',
    question: 'listeners와 advertised.listeners를 다르게 설정해야 하는 경우',
    relatedQuestionCount: 640,
  },
]

export const FAQ_NOTE = '자유 질문 챗봇은 제공하지 않습니다. 정리된 FAQ · Pain Point 목록만 제공합니다.'

/** 우측 카드의 근거 Evidence 요약. 화면 09로 넘어가는 입구다. */
export const SUPPORTING_EVIDENCE = [
  { filePath: 'build.gradle', badge: 'DEP · L0' },
  { filePath: 'KafkaConfig.java:24', badge: 'CFG · L1' },
]
