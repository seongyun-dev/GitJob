import { Outlet } from 'react-router'
import { AppHeader } from '@/app/layouts/AppHeader'

/**
 * 로그인 이후 화면의 단일 반응형 셸.
 *
 * 와이어프레임은 S2·S3을 Mobile, S4·S5를 Web으로 나눠 그렸지만 별도 모바일 앱 없이
 * 반응형 웹 하나로 간다(2026-09-08 FE 결정). 화면별 폭 차이는 각 페이지가
 * Tailwind 브레이크포인트로 처리한다.
 *
 * 치수는 `GitJob Desktop UI Final.html`의 Repository Selection(`section#repos`)
 * computed style에서 그대로 읽었다.
 *   본문 컨테이너 max-width 1328px · padding 40px 48px 88px → 내부 콘텐츠 1232px
 * 이전에 쓰던 `max-w-5xl`(1024px)은 1440~1600px에서 좌우 여백이 과했다.
 *
 * 폭·여백 단계는 `index.css`의 `.gj-shell`이 갖는다. 화면마다 max-width를 따로
 * 적지 않기 위해 셸 한 곳에서만 정한다.
 */

/**
 * 배경. Final `section#repos`의 background를 그대로 옮긴 값이다.
 *
 * 우상단 블루 radial + 좌하단 웜 뉴트럴 radial + 118deg 리니어 세 겹이다. 순백 단색이면
 * 흰 카드와 구분이 없어 CRUD 화면처럼 보이는데, 이 조합이 Landing 히어로와 같은
 * 색 계열(웜 뉴트럴 → 블루)을 유지하면서 명도만 올려 콘텐츠를 방해하지 않는다.
 * 값을 눈대중으로 옅게 바꾸지 않는다. Final이 시각 기준이다.
 */
const APP_BACKDROP = [
  'radial-gradient(780px 560px at 92% 0%,rgba(158,184,221,0.38),rgba(0,0,0,0) 62%)',
  'radial-gradient(620px 460px at 2% 100%,rgba(186,170,159,0.30),rgba(0,0,0,0) 62%)',
  'linear-gradient(118deg,#F1EEEB 0%,#EEEDEE 50%,#E7EDF7 100%)',
].join(',')

export function AppLayout() {
  return (
    <div className="min-h-full text-brand-ink" style={{ background: APP_BACKDROP }}>
      <AppHeader />
      <main className="gj-shell">
        <Outlet />
      </main>
    </div>
  )
}
