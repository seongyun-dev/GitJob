import type { TrendPointFixture, TrendSeriesFixture, TrendSourceFixture } from '@/mocks/types'

/**
 * 기술 트렌드 fixture · 화면 12·13.
 *
 * **출처를 나란히 두되 합치지 않는 것이 이 화면의 규칙이다.** 세 출처의 지표·분모·
 * 기간이 모두 다르므로 종합 점수를 만들지 않는다(`docs/ai/c-public-trend.md` 30행,
 * `docs/ai/c-archive-trend.md` 10행). fixture에 `unit`과 `basis`를 필수로 둔 것이
 * 그 규칙의 장치다 — 단위를 적지 않으면 화면이 세 숫자를 나란히 놓고 비교하게 된다.
 *
 * 값은 확정 디자인의 아트보드 12·13에서 옮겼다. 다만 실제 데이터 계약과 어긋나는
 * 곳이 둘 있어 그대로 옮기지 않고 상태로 표현했다. 아래 각 상수의 주석을 볼 것.
 */

/** 화면 12의 세 출처. 순서가 화면의 열 순서다. */
export const TREND_SOURCES: TrendSourceFixture[] = [
  {
    id: 'JOB',
    label: 'JOB · 채용공고',
    unit: '공고 언급 비중',
    status: 'READY',
    basis: '최근 90일 · 백엔드 공고 87건 · 필수+우대 언급',
    scopeNote: null,
    rows: [
      {
        rank: 1,
        techId: 'kafka',
        techName: 'Apache Kafka',
        share: '19.7%',
        delta: '↑ 7.1%',
        direction: 'UP',
      },
      {
        rank: 2,
        techId: 'spring-boot',
        techName: 'Spring Boot',
        share: '18.4%',
        delta: '↑ 4.2%',
        direction: 'UP',
      },
      {
        rank: 3,
        techId: 'docker',
        techName: 'Docker',
        share: '16.9%',
        delta: '↑ 1.8%',
        direction: 'UP',
      },
      {
        rank: 4,
        techId: 'aws',
        techName: 'AWS',
        share: '15.2%',
        delta: '↓ 0.6%',
        direction: 'DOWN',
      },
      {
        rank: 5,
        techId: 'kubernetes',
        techName: 'Kubernetes',
        share: '12.8%',
        delta: '↑ 2.3%',
        direction: 'UP',
      },
    ],
    footnote: '전월 대비 변화입니다. 필수 언급만 따로 보려면 상세에서 확인하세요.',
  },
  {
    /*
     * Innovation Graph는 **언어 단위 지표만** 준다(`docs/ai/c-public-trend.md`).
     * 그래서 이 열의 순위에는 Kafka·Docker가 없고 언어만 있다. 와이어프레임이
     * `LANGUAGE ONLY`라는 배지를 따로 쓰지만, `DataStatus`에 그런 값이 없고 만들 수도
     * 없다 — 상태는 READY가 맞고, 제한은 `scopeNote`로 말한다.
     */
    id: 'GITHUB',
    label: 'GITHUB · Innovation Graph',
    unit: '언어 사용 비중',
    status: 'READY',
    basis: '최근 분기 · 대한민국 · 언어 단위 지표',
    scopeNote: '언어 단위로만 제공됩니다. Kafka 같은 라이브러리는 NOT_SUPPORTED입니다.',
    rows: [
      {
        rank: 1,
        techId: 'python',
        techName: 'Python',
        share: '23.1%',
        delta: '↑ 1.2%',
        direction: 'UP',
      },
      {
        rank: 2,
        techId: 'javascript',
        techName: 'JavaScript',
        share: '18.6%',
        delta: '↓ 0.9%',
        direction: 'DOWN',
      },
      {
        rank: 3,
        techId: 'typescript',
        techName: 'TypeScript',
        share: '14.2%',
        delta: '↑ 2.0%',
        direction: 'UP',
      },
      {
        rank: 4,
        techId: 'java',
        techName: 'Java',
        share: '11.8%',
        delta: '↓ 0.4%',
        direction: 'DOWN',
      },
      {
        rank: 5,
        techId: 'go',
        techName: 'Go',
        share: '6.3%',
        delta: '↑ 0.7%',
        direction: 'UP',
      },
    ],
    footnote:
      'Kafka · Docker 같은 라이브러리 · 도구는 이 출처에서 NOT_SUPPORTED입니다. 데이터 없음이나 오류가 아니라 지원 범위 밖입니다.',
  },
  {
    /*
     * **와이어프레임과 다르게 둔 곳이다.** 확정 디자인은 Stack Overflow 순위를 값과
     * 함께 그리지만, 데이터 계약은 "Stack Overflow는 현재 입력에 없다"고 적는다
     * (`docs/ai/c-public-trend.md` 10행). 값을 채우면 없는 출처를 있는 것처럼 디자인하게
     * 되므로 `PREPARING`으로 두고 행을 비웠다.
     *
     * 이 출처를 실제로 쓰기로 정해지면 상태를 READY로 바꾸고 행을 채우면 된다.
     * 그때까지 이 열은 "출처가 아직 없을 때 화면이 어떻게 보이는가"를 확인하는 자리다.
     */
    id: 'STACK_OVERFLOW',
    label: 'STACK OVERFLOW',
    unit: '질문 비중',
    status: 'PREPARING',
    basis: '태그 기준 · 최근 12개월',
    scopeNote: '현재 수집 입력에 없는 출처입니다.',
    rows: [],
    footnote:
      '질문량은 관심도가 아니라 "막히는 정도"에 가깝습니다. 하락이 곧 수요 감소를 뜻하지 않습니다.',
  },
]

/*
 * ─────────────────────────────────────────────────────────────────────────────
 * 화면 13 · 기술별 출처 시계열
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * 트렌드 개요(화면 12)의 순위에 오르는 기술 **전부**를 덮는다. 한 기술만 두면 개요에서
 * 다른 기술을 눌렀을 때 빈 화면이 나오는데, 그건 데이터가 없는 것이 아니라 fixture가
 * 없는 것이어서 디자인 판단을 흐린다.
 *
 * **기술 종류에 따라 출처 구성이 달라지는 것이 이 데이터의 핵심이다.**
 *
 *   라이브러리 · 도구 (Kafka · Spring Boot · Docker · AWS · Kubernetes)
 *     JOB              READY          월별 공고 언급 건수
 *     Innovation Graph NOT_SUPPORTED  언어 단위 지표만 제공하므로 지원 범위 밖
 *     Stack Overflow   PREPARING      현재 수집 입력에 없는 출처
 *
 *   언어 (Java · Python · JavaScript · TypeScript · Go)
 *     JOB              READY          월별 공고 언급 건수
 *     Innovation Graph READY          **분기별** UNIQUE_PUSHERS
 *     Stack Overflow   PREPARING      〃
 *
 * 언어의 GitHub 계열을 **분기별**로 둔 것은 지어낸 것이 아니다. Innovation Graph가
 * `year,quarter` CSV를 주고 단위가 `UNIQUE_PUSHERS`이며 분모·비율이 null이다
 * (`docs/ai/c-public-trend.md`). 두 계열을 같은 기간 축에 놓을 수 없다는 사실이 화면에
 * 드러나야 하므로 기간 라벨도 다르게 둔다.
 */

/** JOB 계열의 기간 축. 최근 12개월이고 마지막이 현재 월이다. */
const MONTHS = [
  '10월',
  '11월',
  '12월',
  '1월',
  '2월',
  '3월',
  '4월',
  '5월',
  '6월',
  '7월',
  '8월',
  '9월',
]

/**
 * Innovation Graph 계열의 기간 축. 최근 8분기다.
 *
 * 마지막이 `26 Q2`인 이유는 공식 공개에 시차가 있어 진행 중인 분기(2026-Q3)가 아직
 * 없기 때문이다. 누락 기간을 보간하지 않으므로 없는 분기를 만들어 채우지 않는다.
 */
const QUARTERS = ['24 Q3', '24 Q4', '25 Q1', '25 Q2', '25 Q3', '25 Q4', '26 Q1', '26 Q2']

/** 기간 라벨과 값을 짝짓는다. */
function toPoints(periods: readonly string[], values: readonly number[]): TrendPointFixture[] {
  return values.map((value, index) => ({ period: periods[index] ?? '', value }))
}

/**
 * JOB 계열. 모든 기술이 같은 모양이라 값만 받는다.
 *
 * 축 구성을 기술마다 손으로 쓰지 않는 이유는 열 번 반복되면 한 기술의 단위나 각주가
 * 슬쩍 달라지기 때문이다. 기술마다 달라져야 하는 것은 값뿐이다.
 */
function jobSeries(values: readonly number[], deltaText: string): TrendSeriesFixture {
  const latest = values.at(-1) ?? 0

  return {
    sourceId: 'JOB',
    label: 'JOB · 채용공고',
    status: 'READY',
    axisLabel: '공고 건수',
    latestText: `${latest}건`,
    deltaText,
    points: toPoints(MONTHS, values),
    note: '백엔드 공고 · 월별 · 최근 12개월 · 필수 + 우대 언급 합계',
  }
}

/** 언어의 Innovation Graph 계열. 분기별 UNIQUE_PUSHERS이고 분모·비율이 없다. */
function innovationGraphSeries(values: readonly number[], deltaText: string): TrendSeriesFixture {
  const latest = values.at(-1) ?? 0

  return {
    sourceId: 'GITHUB',
    label: 'GITHUB · Innovation Graph',
    status: 'READY',
    axisLabel: '분기 UNIQUE_PUSHERS',
    latestText: latest.toLocaleString('ko-KR'),
    deltaText,
    points: toPoints(QUARTERS, values),
    note: '대한민국 · 분기별 · 언어 단위. 같은 개발자가 여러 언어에 중복될 수 있어 언어 수치를 합산하지 않습니다.',
  }
}

/**
 * 라이브러리 · 도구의 Innovation Graph 계열.
 *
 * `NO_DATA`가 아니라 `NOT_SUPPORTED`다. 데이터가 없는 것과 그 출처가 애초에 제공하지
 * 않는 것은 다른 사실이며, 화면 15가 둘을 구분하라고 규정한다.
 */
function innovationGraphUnsupported(techName: string): TrendSeriesFixture {
  return {
    sourceId: 'GITHUB',
    label: 'GITHUB · Innovation Graph',
    status: 'NOT_SUPPORTED',
    axisLabel: '분기 UNIQUE_PUSHERS',
    // 지원하지 않는 출처의 값은 null이다. 0으로 채우면 "0이었다"는 다른 사실이 된다.
    latestText: null,
    deltaText: null,
    points: [],
    /*
     * 기술명을 조사 앞에 넣지 않는다. 한국어 조사는 이름의 **한글 읽기** 끝소리에
     * 따라 갈리는데(Kafka → 카프카 → `는`, Python → 파이썬 → `은`) 템플릿은 그것을
     * 알 수 없다. 가운뎃점으로 끊어 조사 문제를 없앤다.
     */
    note: `${techName} · 언어가 아니라 라이브러리 · 도구라서 이 출처의 지원 범위 밖입니다. NO_DATA(데이터 없음)나 FAILED(오류)와는 다른 상태입니다.`,
  }
}

/** Stack Overflow 계열. 모든 기술이 같다 — 출처 자체가 아직 수집 입력에 없다. */
const STACK_OVERFLOW_SERIES: TrendSeriesFixture = {
  sourceId: 'STACK_OVERFLOW',
  label: 'STACK OVERFLOW',
  status: 'PREPARING',
  axisLabel: '질문 비중',
  latestText: null,
  deltaText: null,
  points: [],
  note: '현재 수집 입력에 없는 출처입니다. 준비되면 이 영역에 표시합니다.',
}

/** 기술 하나의 출처별 추이. `techName`을 함께 두어 화면이 제목을 만들 수 있게 한다. */
export interface TechTrendFixture {
  techId: string
  techName: string
  series: TrendSeriesFixture[]
}

export const TECH_TRENDS: TechTrendFixture[] = [
  {
    // 화면 09·10·11·13의 예시 기술. 값은 확정 디자인 아트보드 13에서 그대로 옮겼다.
    techId: 'kafka',
    techName: 'Apache Kafka',
    series: [
      jobSeries([34, 38, 41, 39, 45, 52, 49, 58, 61, 66, 72, 78], '↑ 7.1% 전월 대비'),
      innovationGraphUnsupported('Apache Kafka'),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    techId: 'spring-boot',
    techName: 'Spring Boot',
    series: [
      jobSeries([68, 70, 69, 72, 74, 73, 76, 78, 77, 80, 82, 85], '↑ 3.7% 전월 대비'),
      innovationGraphUnsupported('Spring Boot'),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    techId: 'docker',
    techName: 'Docker',
    series: [
      jobSeries([48, 50, 52, 51, 55, 57, 56, 60, 62, 63, 65, 66], '↑ 1.5% 전월 대비'),
      innovationGraphUnsupported('Docker'),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    // 전월 대비가 내려가는 기술. 하락 표기가 어떻게 보이는지 확인할 자리다.
    techId: 'aws',
    techName: 'AWS',
    series: [
      jobSeries([70, 72, 71, 74, 73, 75, 74, 76, 75, 77, 78, 77], '↓ 1.3% 전월 대비'),
      innovationGraphUnsupported('AWS'),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    techId: 'kubernetes',
    techName: 'Kubernetes',
    series: [
      jobSeries([30, 32, 33, 35, 34, 37, 39, 38, 41, 43, 44, 46], '↑ 4.5% 전월 대비'),
      innovationGraphUnsupported('Kubernetes'),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    // 아래 다섯은 언어라 Innovation Graph가 실제로 값을 준다. 기간이 분기인 것에 주의.
    techId: 'java',
    techName: 'Java',
    series: [
      jobSeries([88, 86, 85, 87, 86, 88, 85, 87, 86, 88, 87, 86], '↓ 1.1% 전월 대비'),
      innovationGraphSeries(
        [41200, 40800, 40100, 39600, 39200, 38900, 38500, 38200],
        '↓ 0.8% 전분기 대비',
      ),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    techId: 'python',
    techName: 'Python',
    series: [
      jobSeries([24, 26, 25, 28, 27, 30, 29, 32, 34, 33, 36, 38], '↑ 5.6% 전월 대비'),
      innovationGraphSeries(
        [52000, 53500, 54800, 56200, 57100, 58400, 59600, 61200],
        '↑ 2.7% 전분기 대비',
      ),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    techId: 'javascript',
    techName: 'JavaScript',
    series: [
      jobSeries([34, 33, 35, 34, 36, 35, 34, 36, 35, 34, 34, 33], '↓ 2.9% 전월 대비'),
      innovationGraphSeries(
        [58000, 57400, 56900, 56100, 55600, 55000, 54300, 53800],
        '↓ 0.9% 전분기 대비',
      ),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    techId: 'typescript',
    techName: 'TypeScript',
    series: [
      jobSeries([18, 19, 21, 20, 23, 24, 26, 25, 28, 30, 31, 33], '↑ 6.5% 전월 대비'),
      innovationGraphSeries(
        [31000, 32400, 33800, 35100, 36400, 37900, 39200, 40800],
        '↑ 4.1% 전분기 대비',
      ),
      STACK_OVERFLOW_SERIES,
    ],
  },
  {
    // 표본이 작은 기술. 막대 12개가 모두 낮을 때 차트가 읽히는지 확인할 자리다.
    techId: 'go',
    techName: 'Go',
    series: [
      jobSeries([6, 7, 6, 8, 7, 9, 8, 10, 9, 11, 10, 12], '↑ 20.0% 전월 대비'),
      innovationGraphSeries(
        [9800, 10100, 10400, 10600, 11000, 11300, 11700, 12100],
        '↑ 3.4% 전분기 대비',
      ),
      STACK_OVERFLOW_SERIES,
    ],
  },
]

/**
 * 화면이 techId로 하나를 고를 때 쓴다.
 *
 * 없는 기술이면 undefined다 — 트렌드 개요에 오르지 않은 기술로 직접 주소를 치면
 * 그렇게 되고, 그 경우 화면은 "추이를 불러올 수 없다"고 말해야 한다.
 */
export function findTechTrend(techId: string): TechTrendFixture | undefined {
  return TECH_TRENDS.find((item) => item.techId === techId)
}

export const TREND_FOOTNOTE =
  '종합 Trend 점수는 제공하지 않습니다. 출처마다 READY · PREPARING · NO_DATA · NOT_SUPPORTED 상태가 따로 표시됩니다.'
