/**
 * 디자인 fixture 스위치.
 *
 * 화면 대부분이 아직 값을 못 받는다. 조회 API가 develop에 없거나(매칭·트렌드 계열)
 * BE 미구현 계약만 있는 상태라(Evidence 계열) 실행하면 `StateCard`만 보인다.
 * 그 상태로는 확정 디자인 `Final v2`의 레이아웃을 맞출 수 없다 — 표의 열 폭, 막대
 * 길이, 긴 기술명 줄바꿈은 값이 있어야 결정된다.
 *
 * 그래서 값을 넣되 **프로덕션 렌더 경로와 분리한다.** 와이어프레임
 * `GitJob_FE_Final_v2_17screens.html` 첫 줄이 "DESIGN MOCK DATA ONLY. DO NOT COPY
 * THESE VALUES INTO PRODUCTION FRONTEND"라고 못 박고, PROJECT 규칙도 FE가 값을
 * 만들어 표시하는 것을 금지한다(`docs/ai/c-public-trend.md`, 각 화면 주석).
 *
 * 분리 방법은 셋이다.
 *   1. fixture는 `src/mocks/` 밖으로 나가지 않는다. `features/`가 이 폴더를 import할
 *      때는 반드시 `withDesignFixture`를 거친다.
 *   2. 기본값은 꺼짐이다. 켜려면 `VITE_DESIGN_FIXTURES=on`을 명시해야 한다.
 *   3. 켜지면 `DesignMockBadge`가 화면에 남는다. 스크린샷만 보고 실제 데이터라고
 *      오해하는 것을 막는 장치이므로 배지를 떼지 않는다.
 *
 * 개발 서버에서 켜는 법 — `FE/.env.local`(gitignore 대상)에 한 줄:
 *
 *     VITE_DESIGN_FIXTURES=on
 *
 * 환경 변수 정의는 인프라 소유라 루트 `.env.example`에는 넣지 않았다
 * (`docs/fe/shared-api-contract.md` 1-5). 이 값은 로컬 디자인 작업 전용이고 배포
 * 파이프라인이 주입하는 값이 아니다.
 */

/**
 * fixture 사용 여부. `'on'` 정확히 일치할 때만 켜진다.
 *
 * truthy 검사를 쓰지 않는 이유는 `VITE_DESIGN_FIXTURES=off`나 `=false`가 켜짐으로
 * 읽히기 때문이다. 값을 잘못 적었을 때 조용히 켜지는 쪽보다 꺼지는 쪽이 안전하다.
 */
export const DESIGN_FIXTURES_ENABLED = import.meta.env.VITE_DESIGN_FIXTURES === 'on'

/**
 * fixture가 켜져 있으면 mock을, 아니면 실제 값을 돌려준다.
 *
 * mock을 함수로 받는 이유는 꺼져 있을 때 fixture 모듈의 계산을 아예 하지 않기
 * 위해서다. 번들에서 빠지지는 않지만(정적 import라) 최소한 실행되지는 않는다.
 *
 * ```ts
 * const profile = withDesignFixture(query.data, () => KAFKA_TEAM_PROFILE)
 * ```
 */
export function withDesignFixture<T>(real: T, fixture: () => T): T {
  return DESIGN_FIXTURES_ENABLED ? fixture() : real
}
