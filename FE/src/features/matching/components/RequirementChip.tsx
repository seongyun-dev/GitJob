import type { JobRequirement, RequirementMark } from '@/features/matching/model/view'

/**
 * 기술요건 대조 칩 · 티켓 S15P21E102-213.
 *
 * 확정 디자인 `Final v2`가 `02 Job Match` · `03 What-if` · `16 Target Role`에서
 * 같은 칩을 쓴다. 네 표시의 의미가 서로 다른 것이 이 컴포넌트의 요점이다.
 *
 *   ✓ 보유          요구 Level 이상의 Personal Evidence가 있다
 *   △ Level 부족    Evidence는 있는데 요구 Level에 미달이다
 *   ✕ Evidence 없음 선언 · 설정 · 구현 어느 것도 확인되지 않았다
 *   ? 판정 못 함     요구를 해석하지 못했거나 그 기술을 평가하지 않았다
 *
 * **`△`와 `✕`를 같은 색으로 칠하지 않는다.** 둘을 묶으면 "없는 기술"과 "있는데
 * 부족한 기술"이 화면에서 구분되지 않고, 그러면 다음에 무엇을 하면 되는지가 사라진다.
 *
 * **`?`를 `✕`로 접지 않는다(S15P21E102-279).** C는 "요구를 해석하지 못했다"와
 * "충족하지 못했다"를 구분해서 준다. 접으면 화면이 판정하지 않은 기술을 미보유로
 * 표시하게 되고, 그것이 인수 조건에서 금지한 동작이다.
 */
const MARK_TEXT: Readonly<Record<RequirementMark, string>> = {
  HAVE: '✓',
  WEAK: '△',
  NONE: '✕',
  UNKNOWN: '?',
}

const MARK_CLASS: Readonly<Record<RequirementMark, string>> = {
  HAVE: 'bg-tone-accent-bg text-tone-accent',
  WEAK: 'bg-tone-caution-bg text-tone-caution',
  NONE: 'border border-brand-line bg-white text-brand-faint',
  UNKNOWN: 'bg-tone-neutral-bg text-tone-neutral',
}

/** 접근성 라벨. 기호만 읽히면 화면 낭독으로는 의미를 알 수 없다. */
const MARK_LABEL: Readonly<Record<RequirementMark, string>> = {
  HAVE: '보유',
  WEAK: 'Level 부족',
  NONE: 'Evidence 없음',
  UNKNOWN: '판정하지 않음',
}

export function RequirementChip({ requirement }: { requirement: JobRequirement }) {
  const { techName, mark, requiredLevel } = requirement

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[7px] px-2.5 py-1 text-[12.5px] font-bold ${MARK_CLASS[mark]}`}
    >
      <span aria-hidden className="text-[11px] font-black">
        {MARK_TEXT[mark]}
      </span>
      <span className="truncate">
        {techName}
        {/*
          요구 Level은 공고가 밝힌 경우에만 붙인다. 밝히지 않은 공고에 L1 같은
          기본값을 붙이면 화면이 없는 요구를 만들어 낸다.
        */}
        {mark === 'WEAK' && requiredLevel !== null && ` · ${requiredLevel} 필요`}
      </span>
      <span className="sr-only">{MARK_LABEL[mark]}</span>
    </span>
  )
}

/** 칩 여러 개를 한 줄로. 좁은 화면에서 접히고 넘치지 않는다. */
export function RequirementChipList({
  requirements,
}: {
  requirements: readonly JobRequirement[]
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {requirements.map((requirement) => (
        <RequirementChip key={requirement.techName} requirement={requirement} />
      ))}
    </div>
  )
}
