/**
 * 랜딩 배경 레이어 · 티켓 S15P21E102-191, 213에서 분리.
 *
 * 색 하나하나가 Final v2의 값이라 유틸리티로 쪼개면 오히려 읽기 어렵다. 톤 토큰
 * 5종은 근거·상태 배지의 의미 체계라 이 연출색과 섞지 않는다(`index.css`).
 *
 * 인트로 오버레이가 같은 배경 위에서 재생돼야 걷힐 때 이음매가 생기지 않아
 * `LandingPage`에서 떼어 왔다. 두 곳이 같은 값을 따로 적고 있으면 한쪽만 고쳐질 때
 * 경계선이 보인다.
 */
export const BACKDROP =
  'linear-gradient(100deg,rgba(60,50,48,.12),transparent 58%),' +
  'radial-gradient(820px 640px at 76% 22%,rgba(125,155,197,.7),transparent 64%),' +
  'radial-gradient(820px 380px at 48% 104%,rgba(186,170,159,.85),transparent 66%),' +
  'radial-gradient(520px 420px at 94% 90%,rgba(212,181,162,.42),transparent 62%),' +
  'radial-gradient(720px 620px at 0% 100%,rgba(166,148,138,.95),transparent 66%),' +
  'linear-gradient(112deg,#A9998F 0%,#B3A69C 22%,#BCB8B7 44%,#C0C0C5 56%,#AABDD9 78%,#9EB8DD 100%)'
