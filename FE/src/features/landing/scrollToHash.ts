import type { MouseEvent } from 'react'

/**
 * 랜딩 안쪽 앵커 이동 · 티켓 S15P21E102-212.
 *
 * **브라우저 기본 동작이 여기서는 듣지 않아 직접 옮긴다.**
 *
 * 랜딩은 문서가 아니라 `.lp-scroll` 컨테이너가 스크롤하고, 그 컨테이너에
 * `scroll-snap-type: y mandatory`가 걸려 있다. 이 조합에서 `<a href="#...">`의 기본
 * 이동은 스크롤을 시작하다가 스냅이 원래 장으로 되돌려 버린다 — 주소창의 해시만
 * 바뀌고 화면은 몇 px만 움직인다(2026-09-11 Chrome에서 확인).
 *
 * `href`는 그대로 둔다. 스크립트가 죽거나 새 탭으로 열 때는 기본 동작이 남아 있어야
 * 하고, 링크의 의미(같은 화면 안의 위치)도 마크업에 드러나야 한다.
 *
 * 주소창은 건드리지 않는다. `history.replaceState`로 해시를 남기면 라우터가 모르는
 * 히스토리 변경이 되고, 그 URL로 다시 들어왔을 때 초기 이동이 같은 스냅 문제를 다시
 * 만난다. 공유용 앵커가 필요해지면 그때 초기 진입 처리를 함께 만든다.
 */
export function handleHashLinkClick(event: MouseEvent<HTMLAnchorElement>): void {
  // 새 탭·새 창·다운로드 같은 브라우저 기본 조작은 가로채지 않는다.
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return
  }

  const href = event.currentTarget.getAttribute('href')
  if (href === null || !href.startsWith('#')) {
    return
  }

  const target = document.getElementById(href.slice(1))
  if (target === null) {
    // 대상이 없으면 기본 동작에 맡긴다. 여기서 삼키면 아무 일도 일어나지 않는다.
    return
  }

  event.preventDefault()

  const container = target.closest('.lp-scroll')
  if (!(container instanceof HTMLElement)) {
    // 스냅 컨테이너 밖이면 스냅과 싸울 일이 없다.
    target.scrollIntoView({ block: 'start' })
    return
  }

  /*
    컨테이너 기준 좌표. `offsetTop`은 `offsetParent`가 무엇이냐에 따라 달라지므로
    두 사각형의 차이로 직접 구한다.
  */
  const top =
    target.getBoundingClientRect().top -
    container.getBoundingClientRect().top +
    container.scrollTop

  /*
    스냅을 잠깐 끄고 **즉시** 옮긴 뒤 되돌린다. 세 줄이 한 작업 안에서 끝나므로
    중간 상태가 화면에 보이지 않고, 되돌릴 시점을 따로 기다릴 필요도 없다.

    부드러운 이동을 쓰지 않는다. mandatory 스냅이 걸린 컨테이너에서 애니메이션
    스크롤은 매 프레임 가장 가까운 스냅 지점으로 끌려가는데, 출발 직후에는 그게 아직
    출발한 장이라 되돌아온다. 스냅을 끈 채 애니메이션하고 도착하면 되돌리는 방법도
    써 봤지만, 도착을 기다리는 동안 탭이 가려지면 브라우저가 애니메이션과
    `requestAnimationFrame`을 멈춰 스냅이 꺼진 채로 남았다(2026-09-11 확인).

    링크 한 번에 한 장을 건너뛰는 이동이라 즉시 옮겨도 어색하지 않고, 무엇보다 어떤
    상황에서도 같은 결과가 나온다. 휠로 굴릴 때의 부드러운 전환은 스냅 자체가 만드는
    것이므로 그대로 남는다.
  */
  const previousSnapType = container.style.scrollSnapType
  container.style.scrollSnapType = 'none'
  container.scrollTo({ top, behavior: 'instant' })
  container.style.scrollSnapType = previousSnapType
}

/**
 * 랜딩 맨 위(히어로)로 이동. "서비스 소개"는 특정 섹션이 아니라 메인 화면을 처음부터
 * 보여준다. `.lp-scroll` 컨테이너를 0으로 옮기되, 위 함수와 같은 이유로 스냅을 잠깐 끄고
 * 즉시 옮긴다. `href="/"`는 그대로 둬 스크립트가 없거나 새 탭으로 열 때 랜딩을 새로 연다.
 */
export function handleLandingTopClick(event: MouseEvent<HTMLAnchorElement>): void {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return
  }

  event.preventDefault()
  // 기본 이동을 막으면 링크가 포커스를 쥔 채 남아 일부 브라우저에서 글자에 텍스트
  // 캐럿(깜박이는 |)이 보인다. 스크롤만 하는 동작이라 포커스를 놓아도 문제없다.
  event.currentTarget.blur()

  const container = document.querySelector('.lp-scroll')
  if (!(container instanceof HTMLElement)) {
    window.scrollTo({ top: 0, behavior: 'instant' })
    return
  }

  const previousSnapType = container.style.scrollSnapType
  container.style.scrollSnapType = 'none'
  container.scrollTo({ top: 0, behavior: 'instant' })
  container.style.scrollSnapType = previousSnapType
}
