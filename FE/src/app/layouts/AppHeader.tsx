import { Link } from 'react-router'

/**
 * 로그인 이후 화면의 서비스 헤더.
 *
 * 치수·색은 `GitJob Desktop UI Final.html`의 Repository Selection 화면
 * (`section#repos > header`) computed style을 그대로 옮겼다.
 *   height 72px · padding 0 48px
 *   background rgba(255,255,255,0.62)
 *   border-bottom 1px solid rgba(224,231,241,0.9)
 *   로고 gap 10px
 *
 * Final은 이 헤더에 `My Evidence · 공고 매칭 · 다음 기술 · 트렌드` 네비게이션과
 * `마지막 분석 오늘 10:42`를 두지만 둘 다 넣지 않았다.
 *   - 네비게이션: 현재 라우터에 그 경로들이 없다. 갈 곳이 없는 메뉴는 동작하지 않는
 *     가짜 기능이다.
 *   - 마지막 분석 시각: 실제 API에 없는 값이다. demo 문자열로 채우지 않는다.
 *     (`GET /analyses/{id}`가 미구현이고 `GET /me`도 없다.)
 * 두 영역을 비워도 로고 정렬과 높이가 유지되도록 구성했다.
 */
export function AppHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-[rgba(224,231,241,0.9)] bg-white/[0.62] backdrop-blur-[14px]">
      {/* 71px + bottom border 1px = Final의 header 총 높이 72px. */}
      <div className="mx-auto flex h-[71px] w-full max-w-[1440px] items-center px-6 lg:px-12">
        <Link to="/" className="flex items-center gap-2.5" aria-label="GitJob 홈으로">
          <span className="grid size-[30px] place-items-center rounded-[10px] bg-[linear-gradient(145deg,#1B2B4A,#4F82FF)] text-[13px] font-extrabold tracking-[-0.03em] text-white shadow-[0_8px_18px_rgba(26,53,110,0.20)]">
            G
          </span>
          <span className="text-[17px] font-extrabold tracking-[-0.035em] text-brand-ink-soft">
            GitJob
          </span>
        </Link>
      </div>
    </header>
  )
}
