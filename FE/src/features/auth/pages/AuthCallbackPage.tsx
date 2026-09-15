import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { DEFAULT_REDIRECT, githubLoginUrl, safeRedirect } from '@/features/auth/api/authUrls'
import { useMe } from '@/features/auth/hooks/useMe'
import { PageHero } from '@/shared/ui/PageHero'

/**
 * OAuth 콜백 안내 화면 · 티켓 S15P21E102-156.
 *
 * BE가 GitHub 콜백 처리를 끝낸 뒤 이 경로로 302한다
 * (`github.oauth.frontend-callback-url`). **이 화면이 없으면 로그인 성공 직후
 * 404가 보인다.** 라우터의 `*`가 받아 NotFound를 그리기 때문이다.
 *
 * **세션 쿠키는 그 302 응답에 이미 실려 있다.** 그래서 이 화면은 로그인을
 * 완성하기 위한 추가 요청을 하지 않는다. 결과를 읽어 목적지로 넘기거나 실패를
 * 안내하는 것뿐이다.
 *
 * 쿼리 계약 — BE `AuthController.frontendUri(status, errorCode, redirectTo)`
 *   status=success  redirectTo=&lt;허용 경로&gt;
 *   status=denied   code=AUTH-403-3
 *
 * 토큰 교환·scope 미승인 실패는 예외로 던져져 BE 콜백 URL에서 JSON으로 직접
 * 응답한다. 즉 이 화면에 도달하는 실패는 사실상 권한 거부뿐이다.
 */
export function AuthCallbackPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  // 콜백 302에 세션 쿠키가 이미 실려 있으므로, 여기서 `/me`를 조회하면 방금 로그인한
  // 사용자의 역할을 알 수 있다. 역할로 목적지를 가른다(관리자 → 관리자 화면).
  const { data: me } = useMe()

  const status = params.get('status')
  const code = params.get('code')
  const target = safeRedirect(params.get('redirectTo'))
  const succeeded = status === 'success'

  useEffect(() => {
    if (!succeeded) {
      return
    }
    if (me === undefined) {
      // 아직 /me 확인 중. 역할을 알아야 목적지를 정하므로 결과를 기다린다.
      return
    }
    // 관리자 계정은 목적지와 무관하게 곧바로 관리자 화면으로 보낸다.
    // replace가 아니면 뒤로 가기가 이 콜백 URL로 돌아온다. 쿼리는 1회용이다.
    if (me?.role === 'ADMIN') {
      navigate('/admin', { replace: true })
      return
    }
    // 관리자가 아니면 `/admin`으로 보내지 않는다(관리자 로그인 링크로 들어온 일반 계정 방지).
    navigate(target === '/admin' ? DEFAULT_REDIRECT : target, { replace: true })
  }, [succeeded, me, target, navigate])

  if (succeeded) {
    return (
      <div>
        <PageHero
          eyebrow="SIGNING IN"
          title="로그인을 완료하고 있습니다"
          description="GitHub 인증이 끝났습니다. 잠시 후 분석 화면으로 이동합니다."
        />
      </div>
    )
  }

  return (
    <div>
      <PageHero
        eyebrow="SIGN IN"
        title="로그인을 완료하지 못했습니다"
        description="GitHub 권한 요청이 승인되지 않아 로그인이 중단되었습니다. 다시 시도할 수 있습니다."
      />

      {/*
        권한 거부는 오류가 아니라 사용자의 선택이다. 그래서 재시도 경로를 함께 둔다.
        오류 코드는 문의용으로만 덧붙인다.

        `StateCard`를 쓰지 않는 이유는 그 어휘가 데이터 상태로 닫혀 있어서다
        (`shared/ui/StateCard`). 인증 거부는 그 목록에 없다.
      */}
      <div className="mt-7 max-w-[560px] rounded-[18px] border border-brand-line bg-white px-5 py-6 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
        <p className="text-[15px] font-[750] tracking-[-0.02em] text-brand-ink">
          GitHub 권한이 승인되지 않았습니다
        </p>
        <p className="mt-1.5 max-w-[64ch] text-[13px] leading-[1.6] text-brand-muted">
          저장소에서 기술 사용 근거를 찾으려면 GitHub 읽기 권한이 필요합니다. 코드는 분석에만
          사용하고 저장하지 않습니다.
        </p>

        <a
          href={githubLoginUrl(target)}
          className="mt-5 inline-block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-[14px] font-bold text-white shadow-[0_14px_30px_rgba(31,60,140,0.34)]"
        >
          GitHub으로 다시 로그인
        </a>

        {code !== null && (
          <p className="mt-4 text-[12px] font-semibold text-brand-faint">오류 코드 {code}</p>
        )}
      </div>
    </div>
  )
}
