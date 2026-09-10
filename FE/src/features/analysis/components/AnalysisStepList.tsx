/**
 * 분석 단계 목록 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `07 Analysis Progress`가 정의한 4단계다. 단계 **이름**은
 * 제품이 무엇을 하는지에 대한 정의라 데이터 없이도 보여줄 수 있다.
 *
 * **완료 여부·처리 건수·퍼센트는 넣지 않는다.** v2의 `✓`, `1,284개 파일`, `72%`,
 * `약 1분 남음`은 전부 상태 조회 API가 있어야 아는 값이고, 그 API가 develop에 없다
 * (S15P21E102-133 진행 중). 지금 채우면 fake production data가 된다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-136(이윤서)에 있다. 시각 적용까지만 한다.
 */
const STEPS = [
  { name: '저장소 확인', detail: '분석 대상 Repository와 기본 브랜치 확인' },
  { name: '파일 구조 분석', detail: '빌드 설정 · 의존성 선언 · 소스 트리 파싱' },
  { name: 'Evidence 판정', detail: '기술별 사용 근거와 Level 판정' },
  { name: '사용자 기여 확인', detail: 'Commit 작성자 대조로 본인 기여 구분' },
] as const

export function AnalysisStepList() {
  return (
    <ol className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
      {STEPS.map((step, index) => (
        <li
          key={step.name}
          className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
        >
          <span className="grid size-6 place-items-center rounded-full bg-tone-neutral-bg text-[11px] font-extrabold text-tone-neutral">
            {index + 1}
          </span>
          <p className="mt-2.5 text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">
            {step.name}
          </p>
          <p className="mt-1 text-[12.5px] leading-[1.55] text-brand-muted">{step.detail}</p>
        </li>
      ))}
    </ol>
  )
}
