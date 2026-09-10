/**
 * 추천 근거 체인 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `10 Next Skill Overview`는 1순위 후보를 가로 5단으로
 * 펼친다(실측 `229.4 · 229.4 · 263.8 · 321.2 · 298.2`).
 *
 *   현재 EVIDENCE → 목표 EVIDENCE → 매칭 변화 → 왜 추천하나 → 무엇을 하면 되나
 *
 * 이 다섯 단계 **이름**은 제품이 무엇을 근거로 추천하는지에 대한 정의라 데이터가
 * 없어도 보여줄 수 있다. 오히려 이 골격이 있어야 "점수가 아니라 근거로 추천한다"는
 * 원칙이 화면에서 읽힌다.
 *
 * **각 칸의 값은 넣지 않는다.** 기술명 · Level · `+15` 같은 증감은 전부 C조가
 * 계산해 돌려주는 값이고 조회 API가 develop에 없다.
 */
const STAGES = [
  { label: '현재 EVIDENCE', hint: '지금 확인된 Level과 그 근거 파일' },
  { label: '목표 EVIDENCE', hint: '어떤 근거가 더 있으면 다음 Level인지' },
  { label: '매칭 변화', hint: '필수 기술을 모두 충족하는 공고가 몇 건 늘어나는지' },
  { label: '왜 추천하나', hint: '요구 빈도 · 선행 기술 충족 여부 등 판단 근거' },
  { label: '무엇을 하면 되나', hint: '근거를 만들 수 있는 구현 방향' },
] as const

export function RecommendationChain() {
  return (
    <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {STAGES.map((stage, index) => (
        <li
          key={stage.label}
          className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
        >
          <div className="flex items-center gap-2">
            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-tone-neutral-bg text-[10px] font-extrabold text-tone-neutral">
              {index + 1}
            </span>
            <p className="text-[10.5px] font-extrabold tracking-[0.1em] text-brand-faint">
              {stage.label}
            </p>
          </div>
          <p className="mt-2 text-[12.5px] leading-[1.55] text-brand-muted">{stage.hint}</p>
        </li>
      ))}
    </ol>
  )
}
