import { Outlet } from 'react-router'

/**
 * 단일 반응형 레이아웃.
 *
 * 와이어프레임은 S2·S3을 Mobile, S4·S5를 Web으로 나눠 그렸지만 별도 모바일 앱 없이
 * 반응형 웹 하나로 간다(2026-09-08 FE 결정). 화면별 폭 차이는 각 페이지가
 * Tailwind 브레이크포인트로 처리한다.
 */
export function AppLayout() {
  return (
    <div className="min-h-full bg-white text-neutral-900">
      <main className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  )
}
