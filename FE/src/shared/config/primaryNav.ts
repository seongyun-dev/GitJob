/**
 * 헤더 내비게이션 · 티켓 S15P21E102-246 · 2단 구성 S15P21E102-291.
 *
 * 랜딩 헤더와 로그인 후 내부 헤더가 **같은 이름·순서·개수·목적지**를 쓰도록 한곳에서
 * 정의한다. 두 곳이 따로 적으면 서비스가 분리된 것처럼 보인다.
 *
 * ## 왜 2단이 되었나
 *
 * 1단일 때는 화면 다섯 개만 상단에 있고 나머지(목표 직무·Skill Gap·What-if·내 기술)는
 * **본문 안의 링크로만** 닿을 수 있었다. 흐름을 한 번 벗어나면 되돌아갈 길이 화면마다
 * 달랐고, 지금 어느 단계에 있는지도 상단이 말해 주지 않았다.
 *
 * 그래서 상단은 **큰 단계 다섯 개**로 두고, 그 단계에 속한 화면을 아래 줄에 편다.
 * 상단 항목 수는 그대로이므로 좁은 화면의 배치는 달라지지 않는다.
 *
 * ## 묶는 기준은 사용자 여정이다
 *
 * 설계 문서 3장의 흐름을 그대로 따른다.
 *
 *     GitHub 분석 → 채용공고 매칭 → 다음 기술 → 기술 트렌드
 *
 * 화면을 종류(목록/상세)로 묶지 않는다. 사용자는 "공고를 보다가 무엇이 부족한지"로
 * 옮겨 가지, "목록 화면에서 다른 목록 화면"으로 옮겨 가지 않는다.
 *
 * ## 상세 화면은 하위에 넣지 않는다
 *
 * `/jobs/:jobId` · `/evidence/:techId` · `/trends/:techId` 처럼 **특정 대상이 있어야
 * 열리는 화면**은 서브 내비게이션 항목이 될 수 없다. 대신 자기 목록 항목의 `match`
 * 접두로 켠다 — 공고 상세를 보는 동안에도 상단은 `채용공고 매칭`, 아래 줄은
 * `공고 대시보드`가 켜져 있어야 한다.
 *
 * 부모에는 `match` 를 되도록 두지 않는다. 자식이 켜지면 부모도 켜지므로(`findActiveNav`)
 * 같은 경로를 두 곳에 적을 이유가 없다.
 *
 * 마이페이지는 이 목록에 없다. 여정의 단계가 아니라 계정 화면이라 프로필 드롭다운에 둔다.
 */

/** 랜딩 소개 섹션의 앵커. 헤더와 랜딩이 같은 값을 써야 링크가 어디론가 간다. */
export const SERVICE_INTRO_HASH = '#service-intro'

export interface NavChild {
  readonly label: string
  readonly to: string
  /** 이 항목을 켜는 추가 경로 접두. 상세 화면이 부모 목록을 켜는 데 쓴다. */
  readonly match?: readonly string[]
}

export type PrimaryNavItem =
  | { readonly label: string; readonly kind: 'intro' }
  | {
      readonly label: string
      /** 단계를 눌렀을 때 가는 곳. 하위 첫 화면과 같다. */
      readonly to: string
      readonly match?: readonly string[]
      readonly children?: readonly NavChild[]
    }

export const PRIMARY_NAV: readonly PrimaryNavItem[] = [
  { label: '서비스 소개', kind: 'intro' },

  /*
   * 1단계 · 내 코드를 읽는다.
   *
   * 진입점은 저장소 선택이다(2026-09-13 결정). 분석 진행(`/analyses/:id`)은 저장소를
   * 고른 뒤에만 열리므로 항목으로 두지 않고 `저장소 선택`의 `match` 로 켠다.
   */
  {
    label: 'GitHub 분석',
    to: '/onboarding/repositories',
    children: [
      { label: '저장소 선택', to: '/onboarding/repositories', match: ['/analyses'] },
      { label: '내 기술', to: '/evidence', match: ['/evidence/'] },
    ],
  },

  /*
   * 2단계 · 채용시장과 맞춰 본다.
   *
   * 기본 화면을 공고 대시보드로 둔다. 목표 직무는 그 대조의 **기준**을 바꾸는 화면이라
   * 먼저 거치는 것이 흐름상 맞지만, 상단에서 이 단계를 누르는 사람은 대개 공고를
   * 보러 온다. 기준을 바꾸고 싶으면 아래 줄에서 한 번 더 누르면 된다.
   */
  {
    label: '채용공고 매칭',
    to: '/jobs',
    children: [
      { label: '공고 대시보드', to: '/jobs', match: ['/jobs/'] },
      { label: '목표 직무', to: '/roles' },
    ],
  },

  /*
   * 3단계 · 무엇을 채울지 정한다.
   *
   * 기술 상세(`/technologies/:techId`)는 추천에서 들어가는 화면이라 `match` 로만 켠다.
   */
  {
    label: '다음 기술',
    to: '/recommendations',
    children: [
      { label: '학습 추천', to: '/recommendations', match: ['/technologies/'] },
      { label: '배웠을 때 변화', to: '/what-if' },
    ],
  },

  /*
   * 4단계 · 시장 전체를 본다.
   *
   * 하위가 하나뿐이라 서브 줄을 그리지 않는다(`children` 없음). 한 칸짜리 서브
   * 내비게이션은 자리만 차지하고 고를 것이 없다.
   */
  { label: '기술 트렌드', to: '/trends', match: ['/trends/'] },
]

/**
 * 지금 경로가 어느 단계인지 찾는다.
 *
 * `to` 는 **정확히 일치**할 때만 켠다. 접두로 비교하면 `/` (랜딩)가 모든 경로를
 * 켜 버린다. 하위 화면은 `match` 접두로 따로 받는다.
 */
export function findActiveNav(pathname: string): PrimaryNavItem | undefined {
  return PRIMARY_NAV.find((item) => {
    if ('kind' in item) {
      return false
    }
    if (item.to === pathname) {
      return true
    }
    if ((item.match ?? []).some((prefix) => pathname.startsWith(prefix))) {
      return true
    }
    /*
     * 하위가 켜지면 부모도 켜진다.
     *
     * 부모 `match` 에 자식 경로를 다시 적지 않으려는 것이다. 두 곳에 같은 경로를
     * 적으면 화면을 옮길 때 한쪽만 고쳐져 상단과 아래 줄이 어긋난다 — 실제로
     * `/evidence` 가 그래서 상단이 꺼진 채 서브 줄도 사라졌다.
     */
    return (item.children ?? []).some((child) => isNavChildActive(child, pathname))
  })
}

/** 서브 항목이 켜져 있는지. 부모와 같은 규칙을 쓴다. */
export function isNavChildActive(child: NavChild, pathname: string): boolean {
  return child.to === pathname || (child.match ?? []).some((prefix) => pathname.startsWith(prefix))
}
