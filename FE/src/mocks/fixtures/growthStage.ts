import type { GrowthStageAxisFixture, GrowthStageFixture, GrowthStageId } from '@/mocks/types'

/**
 * 기술 성장 단계 fixture · S6 초안(트렌드 · 성장 단계).
 *
 * 확정 디자인 17장에는 없는 화면이고 초안 캡처만 있다. 그래서 이 fixture는 다른
 * 파일보다 가정이 많다 — 아래 넷을 알고 쓸 것.
 *
 * 1. **초안의 세 축 중 둘은 지금 데이터가 없다.** "깃허브 star 증가율"은 수집 대상이
 *    아니고(docs·AI 코드 전체에 star 지표가 없다), "질문 점유율"의 Stack Overflow는
 *    "현재 입력에 없다"고 계약이 적는다(`docs/ai/c-public-trend.md` 10행). 그래서
 *    star 축을 GitHub 활동 추이로 바꾸고, 질문 축은 `PREPARING`으로 두었다.
 *    있는 것처럼 값을 채우면 없는 데이터를 전제로 화면이 완성된다.
 *
 * 2. **`stage` 하나를 만드는 계산은 아직 없다.** 세 출처를 묶어 단계를 판정하는 것은
 *    "출처를 합쳐 종합 점수를 만들지 않는다"는 규칙과 부딪히므로 제품 결정이
 *    필요하다. 규칙 기반 분류로 정의하고 축별 근거를 함께 노출하는 형태라면 양립하며,
 *    이 fixture는 그 형태를 전제로 만들었다.
 *
 * 3. **단계는 셋이다.** 초안 캡처에는 `쇠퇴기`가 넷째 칸으로 있지만 뺐다. 특정 기술을
 *    쇠퇴한다고 단정하는 것은 이 제품이 할 판단이 아니고, 근거도 "국내 백엔드 공고
 *    표본에서 언급이 줄었다"까지인데 화면의 라벨은 그보다 훨씬 센 주장을 한다.
 *    같은 이유로 하락 자체는 숨기지 않는다 — 축의 `↓` 표기로 사실만 남긴다.
 *
 * 4. **세 단계를 모두 채운 예시를 둔다.** 한 단계만 있으면 stepper에서 첫 칸과 끝 칸이
 *    활성일 때의 모양을 볼 수 없다. 기술마다의 단계는 실제 판정이 아니라 그 배치를
 *    보기 위한 값이다.
 */

/** stepper 라벨. 순서가 곧 단계 순서다. */
export const GROWTH_STAGE_LABELS: Readonly<Record<GrowthStageId, string>> = {
  EARLY: '초기 확산기',
  GROWING: '성장기',
  MATURE: '성숙기',
}

export const GROWTH_STAGE_ORDER: readonly GrowthStageId[] = ['EARLY', 'GROWING', 'MATURE']

const FOOTNOTE = '질문 수 절대값이 아니라 월별 점유율로 계산합니다.'

/**
 * 채용공고 축. 모든 기술이 같은 모양이라 값만 받는다.
 *
 * 축 구성을 기술마다 손으로 쓰지 않는 이유는 열 번 반복되면 한 기술의 출처 이름이나
 * 단위가 슬쩍 달라지기 때문이다. 기술마다 달라져야 하는 것은 값과 설명뿐이다.
 */
function jobAxis(
  valueText: string,
  deltaText: string,
  direction: 'UP' | 'DOWN',
  note: string,
): GrowthStageAxisFixture {
  return {
    label: '채용공고 언급 추이',
    sourceLabel: 'JOB · 채용공고',
    status: 'READY',
    valueText,
    deltaText,
    direction,
    note,
  }
}

/**
 * 라이브러리 · 도구의 GitHub 축.
 *
 * 초안의 star 증가율을 대체한 축이다. GH Archive 표본의 기간별 활동량이며
 * Innovation Graph 언어 지표와는 **다른 출처**다(`docs/ai/c-archive-trend.md` 10행 —
 * 단위와 기간이 달라 합산하지 않는다).
 */
function archiveAxis(
  valueText: string,
  deltaText: string,
  direction: 'UP' | 'DOWN',
  note: string,
): GrowthStageAxisFixture {
  return {
    label: 'GitHub 저장소 활동 추이',
    sourceLabel: 'GITHUB · GH Archive',
    status: 'READY',
    valueText,
    deltaText,
    direction,
    note,
  }
}

/** 언어의 GitHub 축. Innovation Graph는 언어만 지원하므로 언어에만 쓴다. */
function innovationGraphAxis(
  valueText: string,
  deltaText: string,
  direction: 'UP' | 'DOWN',
  note: string,
): GrowthStageAxisFixture {
  return {
    label: 'GitHub 언어 사용 추이',
    sourceLabel: 'GITHUB · Innovation Graph',
    status: 'READY',
    valueText,
    deltaText,
    direction,
    note,
  }
}

/** 질문 점유율 축. 모든 기술이 같다 — 출처 자체가 아직 수집 입력에 없다. */
const QUESTION_AXIS: GrowthStageAxisFixture = {
  label: '질문 점유율',
  sourceLabel: 'STACK OVERFLOW',
  status: 'PREPARING',
  valueText: null,
  deltaText: null,
  direction: null,
  note: '현재 수집 입력에 없는 출처입니다. 준비되면 이 축이 채워집니다.',
}

export const GROWTH_STAGES: GrowthStageFixture[] = [
  {
    techId: 'kafka',
    techName: 'Apache Kafka',
    stage: 'GROWING',
    verdict: 'Kafka는 성장기입니다',
    advice: '진입 적기 — 지금 배우면 선점',
    axes: [
      jobAxis('19.7%', '↑ 7.1% 전월 대비', 'UP', '최근 90일 백엔드 공고 87건 · 필수 + 우대 언급 비중'),
      archiveAxis(
        '월 12,480 events',
        '↑ 4.4% 전월 대비',
        'UP',
        'GH Archive Top-N 표본의 기간별 활동량. Innovation Graph 언어 지표와 다른 출처입니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'spring-boot',
    techName: 'Spring Boot',
    stage: 'MATURE',
    verdict: 'Spring Boot는 성숙기입니다',
    advice: '기본기 — 없으면 비교에서 빠집니다',
    axes: [
      jobAxis('18.4%', '↑ 4.2% 전월 대비', 'UP', '최근 90일 백엔드 공고 87건 중 74건이 필수로 요구'),
      archiveAxis(
        '월 38,920 events',
        '↓ 0.8% 전월 대비',
        'DOWN',
        '절대량은 크고 변화폭은 작습니다. 성숙기의 전형적인 모양입니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'docker',
    techName: 'Docker',
    stage: 'MATURE',
    verdict: 'Docker는 성숙기입니다',
    advice: '필수 요구 16건 · 우대 요구 22건으로 활용 범위가 넓습니다',
    axes: [
      jobAxis('16.9%', '↑ 1.8% 전월 대비', 'UP', '필수보다 우대로 더 자주 언급됩니다.'),
      archiveAxis(
        '월 31,650 events',
        '↑ 1.1% 전월 대비',
        'UP',
        '활동량이 크고 증가율은 완만합니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'aws',
    techName: 'AWS',
    stage: 'MATURE',
    verdict: 'AWS는 성숙기입니다',
    advice: '요구는 많지만 최근 증가는 멈췄습니다',
    axes: [
      // 두 축이 서로 다른 방향인 경우. 엇갈릴 때의 표시를 확인할 자리다.
      jobAxis('15.2%', '↓ 0.6% 전월 대비', 'DOWN', '언급 비중은 높은 편이고 최근 소폭 하락했습니다.'),
      archiveAxis(
        '월 18,300 events',
        '↑ 0.9% 전월 대비',
        'UP',
        '두 축이 엇갈립니다. 한 축만 보고 단계를 정하지 않습니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'kubernetes',
    techName: 'Kubernetes',
    stage: 'EARLY',
    verdict: 'Kubernetes는 초기 확산기입니다',
    advice: '신입 공고에서는 아직 요구가 적습니다',
    axes: [
      jobAxis('12.8%', '↑ 2.3% 전월 대비', 'UP', '신입~3년 구간에서는 필수 요구가 24건 중 7건입니다.'),
      archiveAxis(
        '월 9,140 events',
        '↑ 6.2% 전월 대비',
        'UP',
        '표본 내 활동량은 작지만 증가율이 큽니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    // 아래 다섯은 언어다. GitHub 축이 GH Archive가 아니라 Innovation Graph다.
    techId: 'java',
    techName: 'Java',
    stage: 'MATURE',
    verdict: 'Java는 성숙기입니다',
    advice: '백엔드 공고 87건 중 86건이 요구합니다',
    axes: [
      jobAxis('86.2%', '↓ 1.1% 전월 대비', 'DOWN', '사실상 모든 백엔드 공고가 요구합니다.'),
      innovationGraphAxis(
        '11.8%',
        '↓ 0.4% 전분기 대비',
        'DOWN',
        '대한민국 · 분기별 언어 사용 비중. 공고 요구와는 다른 축입니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'python',
    techName: 'Python',
    stage: 'GROWING',
    verdict: 'Python은 성장기입니다',
    advice: '백엔드 공고보다 데이터 직무에서 더 자주 요구됩니다',
    axes: [
      jobAxis('6.9%', '↑ 1.4% 전월 대비', 'UP', '백엔드 공고 기준입니다. 데이터 직무에서는 30건 중 30건이 요구합니다.'),
      innovationGraphAxis(
        '23.1%',
        '↑ 1.2% 전분기 대비',
        'UP',
        '언어 사용 비중 1위입니다. 공고 요구 순위와 다른 것은 직무 범위가 다르기 때문입니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'javascript',
    techName: 'JavaScript',
    stage: 'MATURE',
    verdict: 'JavaScript는 성숙기입니다',
    advice: '백엔드 공고에서는 요구가 제한적입니다',
    axes: [
      jobAxis('4.2%', '↓ 0.8% 전월 대비', 'DOWN', '백엔드 공고 기준이라 프론트엔드 수요는 포함되지 않습니다.'),
      innovationGraphAxis(
        '18.6%',
        '↓ 0.9% 전분기 대비',
        'DOWN',
        'TypeScript로 옮겨가는 흐름이 있으나 대체 관계는 판정하지 않습니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'typescript',
    techName: 'TypeScript',
    stage: 'GROWING',
    verdict: 'TypeScript는 성장기입니다',
    advice: '두 축이 같은 방향으로 오르고 있습니다',
    axes: [
      jobAxis('3.8%', '↑ 2.1% 전월 대비', 'UP', '백엔드 공고 기준입니다.'),
      innovationGraphAxis(
        '14.2%',
        '↑ 2.0% 전분기 대비',
        'UP',
        '언어 사용 비중 증가율이 가장 큽니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
  {
    techId: 'go',
    techName: 'Go',
    stage: 'EARLY',
    verdict: 'Go는 초기 확산기입니다',
    advice: '표본이 작아 판정 신뢰 구간이 넓습니다',
    axes: [
      jobAxis('1.9%', '↑ 0.9% 전월 대비', 'UP', '백엔드 공고 87건 중 12건입니다. 표본이 작습니다.'),
      innovationGraphAxis(
        '6.3%',
        '↑ 0.7% 전분기 대비',
        'UP',
        '절대 규모는 작고 방향은 위입니다.',
      ),
      QUESTION_AXIS,
    ],
    footnote: FOOTNOTE,
  },
]

/** 화면이 techId로 하나를 고를 때 쓴다. 없는 기술이면 undefined — 그 상태도 화면이 다뤄야 한다. */
export function findGrowthStage(techId: string): GrowthStageFixture | undefined {
  return GROWTH_STAGES.find((item) => item.techId === techId)
}
