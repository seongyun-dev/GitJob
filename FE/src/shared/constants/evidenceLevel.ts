import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * Evidence Level 표기 · 티켓 S15P21E102-204.
 *
 * **여기만 고치면 되도록 한 곳에 모은다.** Level의 의미를 정하는 것은 FE가 아니라
 * Evidence 등급 정책(S15P21E102-127, 진행 중)이고, 그 정책이 아직 확정되지 않았다.
 *
 * Level은 개발자 숙련도나 점수가 아니라 저장소에서 확인한 코드 근거의 단계다.
 * 사용자가 숫자만 보고 의미를 추측하지 않도록 공통 설명을 이 파일에서 관리한다.
 */

/** 배지에 찍히는 값. 정책과 무관하게 Level 식별자 자체다. */
export const LEVEL_TEXT: Readonly<Record<EvidenceLevel, string>> = {
  L0: 'L0',
  L1: 'L1',
  L2: 'L2',
  L3: 'L3',
}

/**
 * 사용자에게 보여 주는 Level 설명. 실행 성공이나 실제 운영 경험을 주장하지 않고,
 * 정적 분석으로 확인한 코드 범위만 설명한다.
 */
export const LEVEL_MEANING: Readonly<Record<EvidenceLevel, string>> = {
  L0: '의존성이나 라이브러리 선언이 확인된 단계',
  L1: '설정 또는 초기화 코드가 확인된 단계',
  L2: '실제 기능에 사용한 구현 코드가 확인된 단계',
  L3: '설정·튜닝·고급 기능 등 심화 구현이 확인된 단계',
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
