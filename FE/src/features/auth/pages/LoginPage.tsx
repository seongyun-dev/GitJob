import { Link, useSearchParams } from 'react-router'
import { githubLoginUrl, safeRedirect } from '@/features/auth/api/authUrls'
import { BrandLogo } from '@/shared/ui/BrandLogo'
import { BrandSymbol } from '@/shared/ui/BrandSymbol'

/**
 * 로그인 화면 · Final v2 `02 Login` 대응.
 *
 * 시각 기준은 GitHub 연결 화면({@link GithubConnectPage})과 같다 — 같은 배경
 * 그라데이션 · 독립 헤더 · 520px 흰 카드. 이 앱의 로그인은 곧 GitHub OAuth라,
 * 카드의 유일한 동작은 로그인 진입점을 여는 것이다.
 *
 * 헤더 "로그인" 버튼이 지금까지는 곧바로 GitHub으로 302했다. 그 사이에 이 화면을
 * 두어 무엇에 로그인하는지·어떤 권한을 요청하는지 한 번 보여준 뒤 GitHub으로 보낸다.
 *
 * 버튼은 GitHub 표준 사인인 버튼(검정 배경 · 옥토캣)을 쓴다. 파란 브랜드 버튼이 아니라
 * GitHub이 정한 색/모양을 따르는 것이, 어디로 가는 버튼인지 즉시 읽히기 때문이다.
 *
 * `AppLayout` 밖에 둔다. 로그인 전 화면이라 앱 내비게이션이 필요 없고, 로고와 도움말만
 * 있는 독립 화면 구성을 연결 화면과 맞춘다.
 */
export function LoginPage() {
  const [params] = useSearchParams()
  const target = safeRedirect(params.get('redirectTo'))

  return (
    <section className="relative flex min-h-dvh flex-col overflow-hidden bg-[radial-gradient(780px_560px_at_92%_0%,rgba(158,184,221,.38),transparent_62%),radial-gradient(620px_460px_at_2%_100%,rgba(186,170,159,.3),transparent_62%),linear-gradient(118deg,#F1EEEB_0%,#EEEDEE_50%,#E7EDF7_100%)]">
      <header className="relative z-[5] flex h-20 items-center justify-between px-6 lg:px-14">
        <Link to="/" aria-label="GitJob 홈으로" className="flex items-center">
          <BrandLogo className="h-[30px] lg:h-9" />
        </Link>
        {/* 도움말 화면이 없어 링크로 만들지 않는다. 연결 화면과 같은 판단. */}
        <span className="text-[13px] text-brand-faint">도움말</span>
      </header>

      {/* 헤더 아래 남는 공간을 채우고 카드를 세로 중앙에 둔다. pb 로 살짝 위로 올려
          광학적 균형을 맞춘다(정확한 중앙보다 조금 위가 안정적으로 보인다). */}
      <div className="flex flex-1 items-center justify-center px-6 pb-24 lg:px-14">
        <div className="w-full max-w-[520px] rounded-[18px] border border-brand-line bg-white px-6 pt-10 pb-8 text-center shadow-[0_10px_28px_rgba(25,47,81,0.07)] lg:px-10">
          <BrandSymbol className="mx-auto mb-5 h-12" />
          <h1 className="text-[23px] leading-[1.2] font-[750] tracking-[-0.04em] text-brand-ink">
            GitJob 시작하기
          </h1>
          <p className="mt-2.5 text-[13.5px] leading-[1.7] text-brand-muted text-pretty">
            GitHub 계정으로 로그인합니다.
            <br />
            선택한 Repository만 읽기 전용으로 분석합니다.
          </p>

          <a
            href={githubLoginUrl(target)}
            className="mt-6 flex items-center justify-center gap-2.5 rounded-xl bg-[#24292F] px-[22px] py-3.5 text-[14px] font-bold text-white shadow-[0_10px_22px_rgba(20,24,31,0.2)] transition-colors hover:bg-[#1B1F24]"
          >
            <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
            GitHub으로 로그인
          </a>

          <p className="mt-3.5 text-[12px] leading-[1.6] text-brand-faint">
            로그인 시 읽기 전용 권한만 요청합니다. 코드 원문은 저장하지 않으며 GitHub Permalink로만
            연결합니다.
          </p>

          {/*
            관리자 전용 로그인 화면으로 보낸다. 일반 로그인은 GitHub OAuth지만 관리자는
            ID/PW 전용 화면(`/admin/login`)을 쓴다. 라우트라 <Link>(클라이언트 이동).
          */}
          <Link
            to="/admin/login"
            className="mt-6 inline-block text-[13px] text-brand-faint underline underline-offset-2 transition-colors hover:text-brand-muted"
          >
            관리자 로그인
          </Link>
        </div>
      </div>
    </section>
  )
}
