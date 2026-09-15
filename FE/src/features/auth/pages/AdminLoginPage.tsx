import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { adminLogin } from '@/features/auth/api/adminLogin'
import { ME_QUERY_KEY } from '@/features/auth/hooks/useMe'
import { ApiError } from '@/shared/api/client'
import { BrandLogo } from '@/shared/ui/BrandLogo'
import { BrandSymbol } from '@/shared/ui/BrandSymbol'

/**
 * 관리자 전용 ID/PW 로그인 화면.
 *
 * 일반 로그인({@link LoginPage})은 GitHub OAuth지만, 이 화면은 GitHub 없이 관리자
 * 화면에 들어가기 위한 진입점이다(운영/시연용). ID/PW를 입력해 로그인하면 BE가
 * 관리자 세션을 발급하고, 곧바로 관리자 화면(`/admin`)으로 이동한다.
 *
 * 시각 기준은 {@link LoginPage}와 같다 — 같은 배경·헤더·카드. 자격 증명은 요청 본문으로만
 * 보내고 화면 어디에도 저장하지 않는다.
 */
export function AdminLoginPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [id, setId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (submitting) {
      return
    }
    if (id.trim() === '' || password === '') {
      setError('아이디와 비밀번호를 모두 입력해 주세요.')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      await adminLogin(id, password)
      // 세션이 바뀌었으니 헤더의 로그인 상태(useMe)를 새로 읽게 한다.
      await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY })
      navigate('/admin', { replace: true })
    } catch (caught) {
      // 성공 외에는 원인을 구분하지 않는다(BE도 401로 통일). 일반적인 안내만 보인다.
      if (caught instanceof ApiError && caught.status === 401) {
        setError('아이디 또는 비밀번호가 올바르지 않습니다.')
      } else {
        setError('로그인 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.')
      }
      setSubmitting(false)
    }
  }

  return (
    <section className="relative flex min-h-dvh flex-col overflow-hidden bg-[radial-gradient(780px_560px_at_92%_0%,rgba(158,184,221,.38),transparent_62%),radial-gradient(620px_460px_at_2%_100%,rgba(186,170,159,.3),transparent_62%),linear-gradient(118deg,#F1EEEB_0%,#EEEDEE_50%,#E7EDF7_100%)]">
      <header className="relative z-[5] flex h-20 items-center justify-between px-6 lg:px-14">
        <Link to="/" aria-label="GitJob 홈으로" className="flex items-center">
          <BrandLogo className="h-[30px] lg:h-9" />
        </Link>
        <span className="text-[13px] text-brand-faint">도움말</span>
      </header>

      <div className="flex flex-1 items-center justify-center px-6 pb-24 lg:px-14">
        <div className="w-full max-w-[440px] rounded-[18px] border border-brand-line bg-white px-6 pt-10 pb-8 text-center shadow-[0_10px_28px_rgba(25,47,81,0.07)] lg:px-10">
          <BrandSymbol className="mx-auto mb-5 h-12" />
          <h1 className="text-[23px] leading-[1.2] font-[750] tracking-[-0.04em] text-brand-ink">
            관리자 로그인
          </h1>
          <p className="mt-2.5 text-[13.5px] leading-[1.7] text-brand-muted">
            관리자 계정으로 로그인합니다.
          </p>

          <form className="mt-6 text-left" onSubmit={onSubmit} noValidate>
            <label className="block text-[12.5px] font-semibold text-brand-ink-soft" htmlFor="admin-id">
              아이디
            </label>
            <input
              id="admin-id"
              type="text"
              autoComplete="username"
              value={id}
              onChange={(event) => setId(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-brand-line bg-white px-3.5 py-2.5 text-[13.5px] text-brand-ink outline-none transition-colors focus:border-brand-400"
            />

            <label
              className="mt-3.5 block text-[12.5px] font-semibold text-brand-ink-soft"
              htmlFor="admin-password"
            >
              비밀번호
            </label>
            <input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-brand-line bg-white px-3.5 py-2.5 text-[13.5px] text-brand-ink outline-none transition-colors focus:border-brand-400"
            />

            {error !== null && (
              <p className="mt-3 text-[12.5px] text-tone-danger" role="alert">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="mt-5 w-full rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-[22px] py-3.5 text-[14px] font-bold text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)] transition-opacity disabled:opacity-60"
            >
              {submitting ? '로그인 중…' : '로그인'}
            </button>
          </form>
        </div>
      </div>
    </section>
  )
}
