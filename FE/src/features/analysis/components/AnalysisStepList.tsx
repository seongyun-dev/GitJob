import type { AnalysisStepFixture } from '@/mocks/types'

/**
 * 분석 단계 목록 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `07 Analysis Progress`가 정의한 4단계다. 단계 **이름**은
 * 제품이 무엇을 하는지에 대한 정의라 데이터 없이도 보여줄 수 있다.
 *
 * **진행 상태는 호출부가 준다.** v2의 `✓`, `1,284개 파일` 같은 값은 상태 조회 API가
 * 있어야 아는 값이고 그 API가 develop에 없다(S15P21E102-133 진행 중). `steps`를
 * 넘기지 않으면 단계 이름만 남는다 — 그게 현재 develop의 모습이다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-136(이윤서)에 있다. 시각 적용까지만 한다.
 */
const STEPS = [
  { name: '저장소 확인', detail: '분석 대상 Repository와 기본 브랜치 확인' },
  { name: '파일 구조 분석', detail: '빌드 설정 · 의존성 선언 · 소스 트리 파싱' },
  { name: 'Evidence 판정', detail: '기술별 사용 근거와 Level 판정' },
  { name: '사용자 기여 확인', detail: 'Commit 작성자 대조로 본인 기여 구분' },
] as const

/** 상태 표시. 색만으로 구분하지 않도록 기호를 함께 둔다. */
const STATE_MARK: Readonly<Record<AnalysisStepFixture['state'], string>> = {
  DONE: '✓',
  RUNNING: '···',
  WAITING: '',
}

const STATE_CLASS: Readonly<Record<AnalysisStepFixture['state'], string>> = {
  DONE: 'bg-tone-success-bg text-tone-success',
  RUNNING: 'bg-tone-accent-bg text-tone-accent',
  WAITING: 'bg-tone-neutral-bg text-tone-neutral',
}

export function AnalysisStepList({ steps }: { steps?: readonly AnalysisStepFixture[] }) {
  return (
    <ol className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
      {STEPS.map((step, index) => {
        const progress = steps?.[index]

        return (
          <li
            key={step.name}
            className={`rounded-[14px] border px-4 py-3.5 ${
              progress?.state === 'RUNNING'
                ? 'border-brand-line-active bg-tone-accent-bg/30'
                : 'border-brand-line bg-white/70'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span
                className={`grid size-6 place-items-center rounded-full text-[11px] font-extrabold ${
                  progress === undefined ? STATE_CLASS.WAITING : STATE_CLASS[progress.state]
                }`}
              >
                {progress === undefined || progress.state === 'WAITING'
                  ? index + 1
                  : STATE_MARK[progress.state]}
              </span>
              {progress !== undefined && (
                <span className="truncate text-[11px] font-semibold text-brand-faint">
                  {progress.progressText}
                </span>
              )}
            </div>
            <p className="mt-2.5 text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">
              {progress?.title ?? step.name}
            </p>
            <p className="mt-1 text-[12.5px] leading-[1.55] text-brand-muted">
              {progress?.description ?? step.detail}
            </p>
          </li>
        )
      })}
    </ol>
  )
}
