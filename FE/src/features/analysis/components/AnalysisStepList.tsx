import type { AnalysisStepState, AnalysisStepView } from '@/features/analysis/model/analysisProgress'

/**
 * 분석 단계 목록 · 티켓 S15P21E102-204, 서버 단계 연동 S15P21E102-136.
 *
 * 칸의 상태는 이제 서버가 정한다. 예전에는 `steps`를 넘기지 않으면 단계 이름만
 * 남았는데, 그것이 develop 의 모습이었다 — 상태를 알려 줄 API 가 없었기 때문이다.
 * 지금은 `analysis_job.current_stage` 가 어느 칸인지 말해 주므로, 호출부가
 * `analysisSteps()` 로 만든 값을 그대로 넘긴다.
 *
 * 칸이 넷에서 셋으로 줄어든 이유는 `model/analysisProgress` 의 `STEPS` 주석에 있다.
 *
 * 색만으로 구분하지 않도록 기호를 함께 둔다.
 */
const STATE_MARK: Readonly<Record<AnalysisStepState, string>> = {
  DONE: '✓',
  RUNNING: '···',
  WAITING: '',
}

const STATE_CLASS: Readonly<Record<AnalysisStepState, string>> = {
  DONE: 'bg-tone-success-bg text-tone-success',
  RUNNING: 'bg-tone-accent-bg text-tone-accent',
  WAITING: 'bg-tone-neutral-bg text-tone-neutral',
}

export function AnalysisStepList({ steps }: { steps: readonly AnalysisStepView[] }) {
  return (
    <ol className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
      {steps.map((step, index) => (
        <li
          key={step.name}
          className={`rounded-[14px] border px-4 py-3.5 ${
            step.state === 'RUNNING'
              ? 'border-brand-line-active bg-tone-accent-bg/30'
              : 'border-brand-line bg-white/70'
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span
              className={`grid size-6 place-items-center rounded-full text-[11px] font-extrabold ${STATE_CLASS[step.state]}`}
            >
              {step.state === 'WAITING' ? index + 1 : STATE_MARK[step.state]}
            </span>
          </div>
          <p className="mt-2.5 text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">
            {step.name}
          </p>
          <p className="mt-1 text-[12.5px] leading-[1.55] text-brand-muted">{step.detail}</p>
        </li>
      ))}
    </ol>
  )
}
