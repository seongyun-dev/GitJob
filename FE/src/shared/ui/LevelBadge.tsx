import { LEVEL_MEANING, LEVEL_STEP_COUNT, LEVEL_STEPS, LEVEL_TEXT } from '@/shared/constants/evidenceLevel'
import { EVIDENCE_LEVELS } from '@/shared/types/domain'
import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * Level 배지와 사다리 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `08 My Evidence` 표가 Level을 두 겹으로 보여준다.
 *   배지  — 값 자체. 최고 단계(L3)만 Deep Navy로 채우고 나머지는 연한 배경
 *   사다리 — 4칸 막대. 몇 칸이 찼는지로 단계를 한눈에 비교하게 한다
 *
 * 표시 문구는 `constants/evidenceLevel`이 갖는다. 여기서 "구현"·"운영" 같은 의미를
 * 직접 쓰지 않는다. 등급 정책(S15P21E102-127)이 확정되기 전이라 문구를 굳히면
 * 나중에 화면 전체를 다시 손대야 한다.
 *
 * `variant`는 두 열을 구분한다. v2의 표에서 PERSONAL 열은 배지가 진하고
 * REPOSITORY 열은 글자만 놓인다. 같은 값이라도 무엇을 근거로 한 Level인지가
 * 다르므로 시각 무게를 다르게 준다.
 */
export function LevelBadge({
  level,
  variant = 'personal',
}: {
  level: EvidenceLevel
  /** personal: 채운 배지 · repository: 글자만 */
  variant?: 'personal' | 'repository'
}) {
  const filled = level === 'L3'

  if (variant === 'repository') {
    return (
      <span className="text-[12.5px] font-bold text-brand-muted">{LEVEL_TEXT[level]}</span>
    )
  }

  return (
    <span
      className={`inline-flex items-center rounded-lg px-2.5 py-1 text-[12px] font-extrabold ${
        filled
          ? 'bg-brand-ink text-white'
          : 'border border-brand-line bg-tone-accent-bg text-tone-accent'
      }`}
    >
      {LEVEL_TEXT[level]}
    </span>
  )
}

/**
 * Level 사다리. 4칸 중 해당 단계까지 채운다.
 *
 * 칸 수는 정책이 아니라 `EVIDENCE_LEVELS` 배열의 길이에서 나오는 값이라
 * 문구 확정 전에도 쓸 수 있다.
 */
export function LevelLadder({
  level,
  tone = 'accent',
}: {
  level: EvidenceLevel
  tone?: 'accent' | 'neutral'
}) {
  const filled = LEVEL_STEPS[level] + 1
  const on = tone === 'accent' ? 'bg-brand-600' : 'bg-brand-box'

  return (
    <span className="inline-flex items-center gap-[3px]" aria-hidden>
      {Array.from({ length: LEVEL_STEP_COUNT }, (_, index) => (
        <i
          key={index}
          className={`h-[5px] w-3.5 rounded-[2px] ${index < filled ? on : 'bg-[#E4E9F2]'}`}
        />
      ))}
    </span>
  )
}

/**
 * Level 범례.
 *
 * 척도가 L0~L3 네 단계라는 것은 **제품 정의**라 판정 결과가 없어도 보여줄 수 있고,
 * 보여줘야 표의 배지를 읽을 수 있다. 확정 디자인 `Final v2`도 Evidence 화면 아래에
 * 같은 줄을 둔다.
 *
 * 다만 각 단계의 **의미**는 등급 정책(S15P21E102-127)이 정한다. 확정 전이라
 * `LEVEL_MEANING`이 전부 `null`이고, 그동안은 값만 나열한다. 정책이 확정되면
 * constants만 채우면 이 줄에 설명이 따라 붙는다.
 */
export function LevelLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
      {EVIDENCE_LEVELS.map((level) => (
        <span key={level} className="inline-flex items-center gap-2">
          <LevelLadder level={level} />
          <span className="text-[12.5px] font-bold text-brand-muted">{LEVEL_TEXT[level]}</span>
          {LEVEL_MEANING[level] !== null && (
            <span className="text-[12.5px] text-brand-faint">{LEVEL_MEANING[level]}</span>
          )}
        </span>
      ))}
    </div>
  )
}
