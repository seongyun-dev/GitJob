import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * Evidence Level 표기 · 티켓 S15P21E102-204.
 *
 * **여기만 고치면 되도록 한 곳에 모은다.** Level의 의미를 정하는 것은 FE가 아니라
 * Evidence 등급 정책(S15P21E102-127, 진행 중)이고, 그 정책이 아직 확정되지 않았다.
 *
 * 확정 전까지 화면에는 `L0`~`L3` **값만** 쓴다. "없음 / 노출 / 구현 / 운영"이나
 * "선언 / 설정·사용 / 구현 / 반복 구현" 같은 의미 설명을 production copy로 굳히지
 * 않는다. 확정되면 아래 `LEVEL_MEANING`만 채우고 표시 지점은 그대로 두면 된다.
 */

/** 배지에 찍히는 값. 정책과 무관하게 Level 식별자 자체다. */
export const LEVEL_TEXT: Readonly<Record<EvidenceLevel, string>> = {
  L0: 'L0',
  L1: 'L1',
  L2: 'L2',
  L3: 'L3',
}

/**
 * Level의 의미 설명. 정책 확정 전이라 비워 둔다.
 *
 * `null`인 동안 화면은 설명을 렌더하지 않는다. 빈 문자열이 아니라 `null`인 이유는
 * "설명이 없다"와 "설명이 빈 값이다"를 구분하기 위해서다.
 */
export const LEVEL_MEANING: Readonly<Record<EvidenceLevel, string | null>> = {
  L0: null,
  L1: null,
  L2: null,
  L3: null,
}

/**
 * 사다리 눈금. Level을 4칸 막대로 보여줄 때 몇 칸을 채울지만 정한다.
 * 이건 정책이 아니라 `EVIDENCE_LEVELS` 배열의 순서에서 나오는 값이라 확정 전에도 쓸 수 있다.
 */
export const LEVEL_STEPS: Readonly<Record<EvidenceLevel, number>> = {
  L0: 0,
  L1: 1,
  L2: 2,
  L3: 3,
}

/** 사다리 전체 칸 수. */
export const LEVEL_STEP_COUNT = 4
