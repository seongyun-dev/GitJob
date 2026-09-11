import { DESIGN_FIXTURES_ENABLED } from '@/mocks/designFixtures'

/**
 * fixture로 그려진 화면임을 남기는 배지.
 *
 * 확정 디자인도 값이 가짜인 화면에 같은 표시를 달아 둔다(아트보드 14의 `DESIGN MOCK`,
 * 16의 `DESIGN MOCK ROLE TAXONOMY`). 그 표시가 없으면 스크린샷이 팀 채널을 돌 때
 * 실제 분석 결과로 읽힌다 — 이 제품에서 그건 표시 오류가 아니라 사실 왜곡이다.
 *
 * fixture가 꺼져 있으면 아무것도 렌더하지 않으므로 화면에 그냥 두어도 된다.
 * 조건문으로 감싸지 말 것 — 감싸는 순간 배지를 빠뜨린 화면이 생긴다.
 */
export function DesignMockBadge({ label = 'DESIGN MOCK' }: { label?: string }) {
  if (!DESIGN_FIXTURES_ENABLED) {
    return null
  }

  return (
    <span className="inline-flex items-center rounded-[8px] border border-[#F0C27B] bg-[#FFF3DF] px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.12em] text-[#8A5A12]">
      {label}
    </span>
  )
}
