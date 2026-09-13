/**
 * 팀 정보 한 곳.
 *
 * 하단바 · 팀 소개 · 개인정보 처리방침 세 곳이 같은 이름과 같은 메일 주소를 쓴다.
 * 세 파일에 각각 적어 두면 사람이 늘거나 연락처가 바뀔 때 한 곳이 남는다.
 *
 * 조 편성과 담당 영역은 팀이 확정해 전달한 것을 그대로 옮겼다. 커밋 이력으로
 * 추측하지 않았다 — 그건 담당 영역이 아니라 지금까지 만진 범위일 뿐이다.
 */

/** 팀 이름. 화면에 그대로 찍힌다. */
export const TEAM_NAME = '박치기 공룡'

/** 프로젝트 식별자. SSAFY 공통 프로젝트 코드다. */
export const PROJECT_CODE = 'S15P21E102'

/**
 * 팀 대표 메일.
 *
 * 하단바와 처리방침의 문의처가 같아야 한다. 개인정보 문의를 받는 창구를 두 개로
 * 나누면 한쪽이 방치된다.
 */
export const TEAM_EMAIL = 'ssafygitjob@gmail.com'

export type TeamMember = {
  name: string
  /** 팀장 한 명만 `true`. 명단 순서가 아니라 이 값으로 표시한다 */
  lead?: boolean
}

export type TeamGroup = {
  /** `A`·`B`·`C`. 화면에는 `A조`처럼 붙여 쓴다 */
  id: 'A' | 'B' | 'C'
  /** 핵심 책임. 조를 한 마디로 부르는 이름이다 */
  focus: string
  /** 한 줄 역할. 그 조가 무엇을 만들어 내는지 */
  summary: string
  /** 맡는 일. 화면에서 칩으로 늘어놓는다 */
  areas: readonly string[]
  members: readonly TeamMember[]
}

/**
 * 조 편성. 팀이 전달한 요약 표와 같은 A·B·C 순서다.
 *
 * **이 순서는 데이터가 흐르는 순서가 아니다.** 실제 흐름은 A → C → B이고
 * 그쪽은 `TEAM_FLOW`가 따로 갖는다. 둘을 한 배열로 합치면 표의 순서와 흐름의
 * 순서 중 하나는 반드시 틀리게 된다.
 *
 * `areas`는 팀이 전달한 요약 표의 "맡는 일"이다. 각 조의 상세 업무 목록은 이보다
 * 훨씬 길지만 소개 화면에 전부 옮기지 않는다. 화면의 목적은 누가 무엇을 맡는지
 * 알리는 것이지 업무 명세를 붙이는 것이 아니다.
 */
export const TEAM_GROUPS: readonly TeamGroup[] = [
  {
    id: 'A',
    focus: '데이터 엔지니어링 · 분산처리',
    summary:
      '외부 데이터를 수집하고, 대용량으로 저장·분산 처리하여 분석 가능한 데이터로 만듭니다.',
    areas: [
      'Kafka',
      'Spark',
      'Hadoop/HDFS',
      '데이터 수집 파이프라인',
      'Parquet 변환',
      'Streaming',
      'Benchmark',
    ],
    members: [{ name: '안성윤', lead: true }, { name: '정민아' }],
  },
  {
    id: 'B',
    focus: '서비스 · GitHub Evidence · 추천',
    summary:
      '사용자의 GitHub Evidence와 분석된 시장 데이터를 연결해 학습 행동을 추천하고 웹서비스로 제공합니다.',
    areas: [
      'GitHub 연동',
      'Evidence 판정',
      '사용자 프로필',
      'Skill Gap',
      '매칭 공고 변화 계산',
      '프로젝트 추천',
      'Backend/API/UI',
    ],
    members: [{ name: '이윤서' }, { name: '최성보' }],
  },
  {
    id: 'C',
    focus: '데이터 분석 · AI',
    summary:
      '수집·가공된 데이터에서 채용시장 수요, 기술 관계, 트렌드, 막힘 패턴 같은 신호를 만들고 AI로 해석합니다.',
    areas: [
      '기술명 정규화',
      '채용공고 기술 분석',
      'Stack Overflow 분석',
      'GitHub Trend',
      '기술 관계·막힘 패턴',
      'AI 설명',
      'RAG',
    ],
    members: [{ name: '김륜영' }, { name: '이송민' }],
  },
]

/**
 * 조 사이의 데이터 흐름.
 *
 * A조가 수집·분산처리한 데이터를 C조가 분석하고, 그 결과를 B조가 서비스로 낸다.
 * 세 조가 나란히 있는 것이 아니라 한 줄로 이어져 있다는 것이 이 팀 구조의 핵심이라
 * 화면에도 그대로 보여준다.
 *
 * `TEAM_GROUPS`를 인덱스로 참조하지 않고 id와 라벨을 직접 적는다. 두 배열을 인덱스로
 * 짝지으면 한쪽 순서만 바뀌었을 때 조용히 어긋난다.
 */
export const TEAM_FLOW: readonly { id: TeamGroup['id']; label: string }[] = [
  { id: 'A', label: '수집 · 분산처리' },
  { id: 'C', label: '분석 · AI' },
  { id: 'B', label: '서비스 · 추천' },
]

/** 전체 명단. 조 편성에서 펼친 것이라 따로 적지 않는다 — 두 곳에 적으면 어긋난다. */
export const TEAM_MEMBERS: readonly TeamMember[] = TEAM_GROUPS.flatMap((group) => group.members)
