/**
 * 랜딩 직무 적합 데이터 · Landing Redesign (직무적합 축).
 *
 * **여기 있는 것은 전부 저장소에서 나온 실제 값이다.** 로그인 전 화면이라 사용자
 * 데이터는 하나도 없지만, 반대쪽 절반(직무와 기술)은 조회 없이도 진짜다. 랜딩은
 * 그 비대칭 위에 서 있다 — 시장 쪽은 채워 두고 내 쪽은 비워 두고, 그 빈칸이 CTA가 된다.
 *
 * ## 직무
 *
 * `AI/job/cohort.py`의 `_ROLE_ALIASES` 다섯 개를 그대로 쓴다. C조 코호트가 공고를
 * 직무로 가르는 실제 기준이므로, 랜딩이 다른 이름을 쓰면 로그인 후 화면과 어긋난다.
 *
 * `FE/src/mocks/fixtures/targetRole.ts`에 `backend`/`data`/`devops`라는 다른 분류가
 * 있는데 그 파일 주석이 스스로 "`DESIGN MOCK ROLE TAXONOMY` · 확정된 목록이 아니다"
 * 라고 적고 있다. 확정 전까지는 코드 쪽을 따른다.
 *
 * ## 기술
 *
 * `AI/registry/data/technology_registry_20260911_4.json`(`registry-20260911.4`)의
 * ACTIVE 44개에서 각 직무의 `categories`에 해당하는 것만 뽑았다. `total`은 그 수를
 * 그대로 센 값이다.
 *
 * 보여 줄 다섯 개는 **그 직무에 고유한 순서**로 골랐다 — 속한 카테고리 수가 적을수록
 * 그 직무를 더 잘 가리킨다(Spring Boot는 백엔드에만, Java는 백엔드와 AI·데이터 양쪽).
 * 같은 수끼리는 Registry 파일 순서를 지킨다.
 *
 * **이것은 채용 수요 순위가 아니다.** 어떤 기술이 공고에 몇 번 나오는지는 C조가
 * 따로 계산하고(S15P21E102-29), 그 스냅샷은 아직 FE에 없다. 그래서 화면에서도
 * 순위처럼 보이지 않게 목록이 아니라 칩으로 늘어놓는다. 스냅샷이 오면 `techs`를
 * 요구 건수와 함께 교체하면 된다.
 */

export type RoleKey = 'BACKEND' | 'FRONTEND' | 'AI_DATA' | 'INFRASTRUCTURE' | 'MOBILE'

export type RoleFit = {
  key: RoleKey
  label: string
  summary: string
  /** 이 직무에서 GitJob이 판정할 수 있는 기술 수. Registry에서 센 실제 값이다. */
  total: number
  /** 그중 화면에 보여 주는 것. 나머지는 `total - techs.length`로 계산해 적는다. */
  techs: readonly string[]
}

/**
 * 칩이 놓이는 순서. 화면에 보이는 차례를 여기 한 곳에서 정한다.
 *
 * 아래 `ROLE_FIT`을 정본으로 두고 배열을 파생시키는 이유는 조회 때문이다. 배열에서
 * `find`로 꺼내면 타입이 `RoleFit | undefined`가 되어 호출부마다 없을 때를 처리해야
 * 하는데, 다섯 직무는 `RoleKey` 유니온이 전부 덮고 있어 없을 수가 없다.
 */
const ROLE_ORDER = ['BACKEND', 'FRONTEND', 'AI_DATA', 'INFRASTRUCTURE', 'MOBILE'] as const

/** 키로 바로 꺼내는 정본. 객체로 적어 두면 없는 키가 타입에서 막힌다. */
export const ROLE_FIT: Record<RoleKey, RoleFit> = {
  BACKEND: {
    key: 'BACKEND',
    label: '백엔드',
    summary: 'Server · API · Data',
    total: 29,
    techs: ['Spring Framework', 'Spring Boot', 'JPA', 'MyBatis', 'Node.js'],
  },
  FRONTEND: {
    key: 'FRONTEND',
    label: '프론트엔드',
    summary: 'UI · Web · Rendering',
    total: 7,
    techs: ['HTML', 'CSS', 'React', 'Vue.js', 'Next.js'],
  },
  AI_DATA: {
    key: 'AI_DATA',
    label: 'AI · 데이터',
    summary: 'Pipeline · Model · Analysis',
    total: 17,
    techs: ['NumPy', 'pandas', 'scikit-learn', 'PyTorch', 'TensorFlow'],
  },
  INFRASTRUCTURE: {
    key: 'INFRASTRUCTURE',
    label: '인프라',
    summary: 'Container · Cloud · CI',
    total: 14,
    techs: ['Docker', 'Kubernetes', 'Jenkins', 'Apache Hadoop', 'AWS'],
  },
  MOBILE: {
    key: 'MOBILE',
    label: '모바일',
    summary: 'App · Client',
    total: 3,
    techs: ['Unity', 'C#', 'Kotlin'],
  },
}

/** 화면에 늘어놓을 순서대로. */
export const ROLE_FITS: readonly RoleFit[] = ROLE_ORDER.map((key) => ROLE_FIT[key])
