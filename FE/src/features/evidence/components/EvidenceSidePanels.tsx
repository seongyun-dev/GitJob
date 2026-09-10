import { StateCard } from '@/shared/ui/StateCard'

/**
 * Evidence 화면 우측 패널 2종 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `08 My Evidence`는 372px 패널에 두 블록을 쌓는다.
 *   근거 보강 필요  — 저장소엔 있지만 내 Commit에는 없는 기술
 *   ANALYSIS CONTEXT — 어떤 저장소를 분석했는지와 본인 Commit 비중
 *
 * 두 블록 모두 값은 조회 API가 준다. 여기서는 무엇이 들어올 자리인지만 세운다.
 * v2의 `Spring Boot L2 — L3`나 `본인 Commit 62%`는 demo 값이라 옮기지 않는다.
 */

/**
 * Personal Level이 Repository Level보다 낮은 기술이 모이는 자리.
 *
 * 이 구분이 이 제품의 핵심이다. "저장소에 구현은 있는데 내 Commit 근거가 없다"는
 * 것은 기술이 없다는 뜻이 아니라 **판정 범위가 다르다**는 뜻이라, 부족한 기술과
 * 섞어 보여주면 사용자가 자기 상태를 잘못 읽는다.
 */
export function ReinforcementPanel() {
  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
        근거 보강 필요
      </p>
      <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
        저장소엔 있지만 내 Commit에는 없는 기술
      </h2>
      <div className="mt-4">
        <StateCard
          kind="PREPARING"
          title="아직 판정 결과가 없어요"
          description="Personal Level이 Repository Level보다 낮은 기술이 이 자리에 모입니다. 부족한 기술과는 구분해 표시합니다."
        />
      </div>
    </section>
  )
}

/**
 * 분석 맥락. 어떤 저장소를 근거로 판정했는지 밝힌다.
 *
 * Level만 보여주고 근거 범위를 감추면 "왜 이 Level인가"에 답할 수 없다.
 */
export function AnalysisContextPanel() {
  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
        ANALYSIS CONTEXT
      </p>
      <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
        무엇을 근거로 판정했나
      </h2>
      <div className="mt-4">
        <StateCard
          kind="NO_DATA"
          title="아직 분석한 저장소가 없어요"
          description="분석에 포함된 저장소와 저장소별 본인 Commit 비중이 여기에 표시됩니다."
        />
      </div>
      <p className="mt-4 text-[12.5px] leading-[1.6] text-brand-faint">
        분석 시각과 Snapshot 기준은 결과가 생기면 이 아래에 남습니다.
      </p>
    </section>
  )
}
