import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { githubLoginUrl } from '@/features/auth/api/authUrls'
import { useMe } from '@/features/auth/hooks/useMe'
import { analysisStartMode } from '@/features/landing/model/analysisStart'

/** 로그인 상태를 확인한 뒤 OAuth 또는 저장소 선택으로 보내는 랜딩 공통 CTA. */
export function AnalysisStartLink({
  className,
  children,
}: {
  className: string
  children: ReactNode
}) {
  const { data: me } = useMe()
  const mode = analysisStartMode(me)

  if (mode === 'CHECKING') {
    return (
      <span aria-busy="true" aria-disabled="true" className={`${className} cursor-wait opacity-70`}>
        {children}
      </span>
    )
  }

  if (mode === 'REPOSITORY_SELECTION') {
    return (
      <Link to="/onboarding/repositories" className={className}>
        {children}
      </Link>
    )
  }

  if (mode === 'GITHUB_CONNECT') {
    return (
      <Link to="/onboarding/github" className={className}>
        {children}
      </Link>
    )
  }

  // OAuth 엔드포인트의 302를 따라가야 하므로 비로그인 경로만 최상위 이동을 사용한다.
  return (
    <a href={githubLoginUrl()} className={className}>
      {children}
    </a>
  )
}
