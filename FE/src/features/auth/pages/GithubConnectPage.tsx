import { useSearchParams } from 'react-router'
import { githubLoginUrl, safeRedirect } from '@/features/auth/api/authUrls'
import { BrandLogo } from '@/shared/ui/BrandLogo'

/**
 * GitHub 권한 재요청 안내 화면 · 티켓 S15P21E102-156.
 *
 * 시각 기준: Final v2 `section#connect`(03 GitHub Connect).
 *   배경 그라데이션 · 헤더 80px / 로고 30px · 카드 520px
 *   카드 #fff / 1px #E0E7F1 / radius 18px / shadow 0 10px 28px rgba(25,47,81,.07)
 *   padding 36px 40px 32px
 *
 * 저장된 Access Token이 폐기·만료되면 저장소 목록(티켓 116·117)과 분석 요청(118)이
 * `AUTH-401-4`로 끊긴다. `AUTH-403-3`·`AUTH-403-4`도 같다. `errorCodes.ts`가 그 세
 * 코드를 `RECONNECT_GITHUB`으로 묶고, `app/providers.tsx`의 전역 가드가 어느 화면에서
 * 걸리든 이 경로로 보낸다.
 *
 * 버튼은 **로그인 진입점을 그대로 연다.** 별도의 재연결 엔드포인트는 두지 않는다 —
 * `completeLogin`의 upsert가 기존 사용자 갈래에서도 `access_token`을 저장하므로
 * 로그인 자체가 이미 토큰 갱신이다. 이 화면이 하는 일은 분석이 왜 멈췄는지 설명하고
 * 다시 시작할 지점을 주는 것이다.
 *
 * `AppLayout` 밖에 둔다. Final v2의 이 아트보드는 앱 내비게이션 없이 로고와 도움말만
 * 있는 독립 화면이고, 권한을 다시 받는 한 가지 일에 집중시키는 구성이다.
 *
 * Final v2에서 가져오지 않은 것
 *   - 단계 인디케이터: 이 화면은 온보딩 2단계가 아니라 권한이 끊긴 뒤의 복구 지점이다
 *   - `나중에 하기`·`← 이전`: GitHub 권한이 없으면 분석이 되지 않아 보낼 곳이 없다.
 *     동작하지 않는 컨트롤을 두지 않는다
 *   - `연결 전` 배지: 연결 상태를 알려면 조회 API가 필요한데 아직 없다
 *     (`MyPage`가 같은 이유로 상태를 주장하지 않는다)
 */

/** 요청 권한. Final v2 `요청 권한 · 읽기 전용` 패널의 항목을 그대로 쓴다. */
const REQUESTED_SCOPES = [
  'Repository 목록과 메타데이터',
  '파일 구조와 설정 파일',
  'Commit 작성자 정보 (본인 기여 판정용)',
] as const

export function GithubConnectPage() {
  const [params] = useSearchParams()
  const target = safeRedirect(params.get('redirectTo'))
  const code = params.get('code')

  return (
    <section className="relative min-h-dvh overflow-hidden bg-[radial-gradient(780px_560px_at_92%_0%,rgba(158,184,221,.38),transparent_62%),radial-gradient(620px_460px_at_2%_100%,rgba(186,170,159,.3),transparent_62%),linear-gradient(118deg,#F1EEEB_0%,#EEEDEE_50%,#E7EDF7_100%)]">
      <header className="relative z-[5] flex h-20 items-center justify-between px-6 lg:px-14">
        {/* Final v2 연결 화면 헤더는 로고 30px. */}
        <BrandLogo className="h-[30px]" />
        {/* 도움말 화면이 없어 링크로 만들지 않는다. Final v2도 `← 이전`을 함께 두지만
            그 목적지는 이전 온보딩 단계다. 여기는 분석이 끊긴 지점에서 온 화면이라
            되돌아가도 같은 실패를 다시 만난다. */}
        <span className="text-[13px] text-brand-faint">도움말</span>
      </header>

      <div className="grid place-items-center px-6 pb-20 lg:px-14">
        <div className="w-full max-w-[520px] rounded-[18px] border border-brand-line bg-white px-6 pt-9 pb-8 shadow-[0_10px_28px_rgba(25,47,81,0.07)] lg:px-10">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            GITHUB ACCESS
          </p>
          <h1 className="mt-2.5 text-[28px] leading-[1.2] font-[750] tracking-[-0.04em] text-brand-ink">
            GitHub 권한 다시 허용
          </h1>

          <p className="mt-3 text-[15px] leading-[1.7] text-brand-muted">
            GitHub 권한이 만료되었거나 해제되어 Repository 분석을 이어갈 수 없습니다. 권한을 다시
            허용하면 지금 계정 그대로 이용할 수 있습니다.
          </p>

          <div className="mt-[22px] overflow-hidden rounded-[14px] border border-[#E8EDF4]">
            <p className="bg-[#F6F8FC] px-4 py-[11px] text-[12px] font-[750] tracking-[0.04em] text-brand-muted">
              요청 권한 · 읽기 전용
            </p>
            <ul>
              {REQUESTED_SCOPES.map((scope) => (
                <li
                  key={scope}
                  className="flex items-center gap-2.5 border-t border-[#E8EDF4] px-4 py-[13px] text-[14px] text-brand-ink-soft"
                >
                  <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-brand-400" />
                  {scope}
                </li>
              ))}
            </ul>
          </div>

          <a
            href={githubLoginUrl(target)}
            className="mt-6 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-[22px] py-[15px] text-center text-[14px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
          >
            GitHub 권한 다시 허용
          </a>

          <p className="mt-4 text-[12.5px] leading-[1.6] text-brand-faint">
            연결 후에도 분석할 Repository는 직접 선택합니다. 코드 원문은 저장하지 않으며 GitHub
            Permalink로만 연결합니다.
          </p>

          {code !== null && (
            <p className="mt-3 text-[12px] font-semibold text-brand-faint">오류 코드 {code}</p>
          )}
        </div>
      </div>
    </section>
  )
}
