import {
  MAIN_PATH,
  browserLandingSeenStorage,
  markLandingSeen,
} from '@/features/landing/model/landingEntry'

/**
 * 랜딩에서 메인으로 나가는 링크 · 티켓 S15P21E102-298, 진입 정책 S15P21E102-310.
 *
 * 목적지는 메인 화면(`/main`)이다. 스토리는 "이 서비스가 무엇인가"를 말하고, 거기서
 * 다음에 알고 싶은 것은 "그래서 내 직무는 무엇을 요구하나"다 — 그 답이 메인 화면이고,
 * 로그인 없이도 볼 수 있다. 로그인 화면으로 바로 보내지 않는다. 아직 무엇을 얻는지 보지
 * 못한 사람에게 GitHub 권한부터 요구하는 순서가 되기 때문이다.
 *
 * <h2>왜 경로가 아니라 링크 속성을 돌려주나</h2>
 *
 * 나가는 순간이 곧 "소개를 확인했다"는 시점이다. 그 표식을 남기지 않으면 다음 방문에서
 * 다섯 장을 다시 지나야 한다.
 *
 * 표식을 남기는 곳은 랜딩에 네 군데(로고 · 헤더 버튼 · 1장 CTA · 5장 CTA)다. 네 곳에
 * 각자 `onClick` 을 적으면 한 곳을 빠뜨렸을 때 "가끔만 기억하는" 상태가 되고, 그것은
 * 화면을 눌러 보기 전에는 드러나지 않는다. 그래서 목적지와 부수효과를 한 쌍으로 묶어
 * 여기서 내보내고, 부르는 쪽은 `<Link {...useStartLink()} />` 로 펼친다.
 *
 * `/main` 에 도달했다는 사실만으로는 남기지 않는다. 외부 링크나 주소창으로 메인에 바로
 * 온 사람은 소개를 본 것이 아니므로, 이후 `/` 진입에서 한 번은 보여줄 수 있어야 한다.
 */
export function useStartLink(): { to: string; onClick: () => void } {
  return {
    to: MAIN_PATH,
    onClick: () => markLandingSeen(browserLandingSeenStorage()),
  }
}
