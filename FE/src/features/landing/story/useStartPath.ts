import { MAIN_PATH } from '@/features/landing/story/storyScenes'

/**
 * 랜딩의 시작 버튼이 가는 곳 · 티켓 S15P21E102-298.
 *
 * 메인 화면(`/main`)이다. 스토리는 "이 서비스가 무엇인가"를 말하고, 거기서 다음에
 * 알고 싶은 것은 "그래서 내 직무는 무엇을 요구하나"다 — 그 답이 메인 화면이고, 로그인
 * 없이도 볼 수 있다.
 *
 * 로그인 화면으로 바로 보내지 않는다. 아직 무엇을 얻는지 보지 못한 사람에게 GitHub
 * 권한부터 요구하는 순서가 되기 때문이다. 로그인은 메인 화면에서 "내 근거 채우러
 * 가기"를 누를 때 필요해진다.
 */
export function useStartPath(): string {
  return MAIN_PATH
}
