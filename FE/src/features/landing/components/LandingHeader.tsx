import { githubLoginUrl } from '@/features/auth/api/authUrls'
import { NAV_LABELS } from '@/features/landing/landingPreviewData'

/**
 * Landing 전용 헤더. 유리 배경 위에 얹히는 흰 글씨 조합이라
 * 로그인 후 화면의 헤더와 톤이 달라 공용으로 올리지 않는다.
 *
 * 내비게이션 항목은 아직 목적지 라우트가 없다. 눌리지 않는 텍스트로 두어
 * 죽은 링크를 만들지 않는다.
 *
 * 로그인 버튼은 티켓 156에서 연결했다. 비활성으로 둔 근거가 "인증 흐름 확정 후"였고,
 * GitHub 단독 로그인으로 확정되어 조건이 풀렸다.
 *
 * `<a>`인 것은 진입 엔드포인트가 302로 GitHub에 넘기기 때문이다. 브라우저 최상위
 * 이동이어야 하므로 `<button onClick>`으로 `fetch`하면 안 된다.
 */
export function LandingHeader() {
  return (
    <header className="lp-rise relative z-[5] flex h-[72px] items-center justify-between lg:h-[88px]">
      <div className="flex items-center gap-3">
        <div className="grid h-[34px] w-[34px] place-items-center rounded-[11px] bg-[linear-gradient(145deg,#1B2B4A,#4F82FF)] text-[15px] font-extrabold tracking-[-0.03em] text-white shadow-[0_10px_22px_rgba(26,53,110,0.22)]">
          G
        </div>
        <span className="text-[21px] font-extrabold tracking-[-0.035em] text-white">GitJob</span>
      </div>

      <nav className="hidden items-center gap-[38px] text-sm font-medium text-white/85 lg:flex">
        {NAV_LABELS.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </nav>

      <a
        href={githubLoginUrl()}
        className="rounded-xl border border-white/40 bg-white/10 px-5 py-[11px] text-[13.5px] font-bold text-white backdrop-blur-[14px] transition-colors hover:bg-white/20"
      >
        로그인
      </a>
    </header>
  )
}
