import type { ReactNode } from 'react'
import { lookupLabel } from '@/shared/ui/lookupLabel'

/**
 * 데이터 상태 카드 · 티켓 S15P21E102-192.
 *
 * `GitJob Desktop UI Final.html`의 `section#states`(SYSTEM STATES)를 그대로 옮겼다.
 * 그 섹션이 규정한 원칙이 이 컴포넌트의 존재 이유다.
 *
 *   "데이터가 없는 상태와 실제 오류는 색과 문구로 구분합니다.
 *    중립(회색) = 데이터 범위의 문제, Warning = 대기 · 부분, Danger = 실패."
 *
 * 카드 치수도 Final 값이다. padding 20px · radius 18px · border 1px #E0E7F1 ·
 * 흰 배경 · shadow rgba(25,47,81,0.07) 0 10px 28px.
 *
 * `QueryStatePanel`과 역할이 다르다. 그쪽은 `ApiError.code`를 화면 행동으로 바꾸는
 * 오류 전용이고, 이쪽은 "데이터가 어떤 상태인가"를 표현한다. 아직 API가 없는 화면이
 * 오류가 아닌 준비 중 상태를 보여줄 곳이 필요해서 만들었다.
 *
 * 값 목록을 닫아 둔다. 임의 문자열을 받으면 화면마다 다른 상태 어휘가 생기고
 * Final이 정한 색 규칙이 무의미해진다. 새 상태가 필요하면 Final을 먼저 확인한다.
 *
 * 최소 높이와 padding 단계는 `index.css`의 `.gj-state-card`가 갖는다. 큰 화면에서
 * 카드가 납작해지면 콘텐츠가 상단에만 몰려 아래가 비어 보이기 때문이다.
 */
export type StateKind =
  /** 조회 중. Final은 스피너 단독 사용을 금지하고 구조를 먼저 보여주라고 규정한다 */
  | 'LOADING'
  /** 조건에 맞는 결과가 없다. 오류가 아니다 */
  | 'EMPTY'
  /** 조회 실패 */
  | 'ERROR'
  /** 일부만 완료됨 */
  | 'PARTIAL'
  /** 호출 한도 대기 */
  | 'RATE_LIMITED'
  /** 아직 제공되지 않는 지표. 이번 초안에서 API가 없는 화면이 쓰는 상태다 */
  | 'PREPARING'
  /** 판정할 근거가 부족하다 */
  | 'INSUFFICIENT_DATA'
  /** 해당 출처에 데이터가 없다. 오류가 아니다 */
  | 'NO_DATA'

type Tone = 'neutral' | 'caution' | 'danger'

const TONES: Readonly<Record<StateKind, Tone>> = {
  LOADING: 'neutral',
  EMPTY: 'neutral',
  ERROR: 'danger',
  PARTIAL: 'caution',
  RATE_LIMITED: 'caution',
  PREPARING: 'caution',
  INSUFFICIENT_DATA: 'neutral',
  NO_DATA: 'neutral',
}

const TONE_CLASSES: Readonly<Record<Tone, string>> = {
  neutral: 'bg-tone-neutral-bg text-tone-neutral',
  caution: 'bg-tone-caution-bg text-tone-caution',
  danger: 'bg-tone-danger-bg text-tone-danger',
}

export function StateCard({
  kind,
  title,
  description,
  meta,
  action,
}: {
  kind: StateKind
  title: string
  description: string
  /**
   * 배지 오른쪽 보조 표기. Final `#states`가 상태마다 갖는 자리다(`L0` · `14:25` · `—`).
   * 정적 문자열만 받는다. 여기에 버튼을 넣지 않는다. 동작하지 않는 컨트롤을 만들지 않기 위해서다.
   */
  meta?: string
  action?: ReactNode
}) {
  const tone = lookupLabel(TONES, kind, 'StateCard')
  if (!tone) {
    return null
  }

  return (
    <div
      className="gj-state-card flex flex-col rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
      role={kind === 'ERROR' ? 'alert' : kind === 'LOADING' ? 'status' : undefined}
      aria-live={kind === 'LOADING' ? 'polite' : undefined}
    >
      {/*
        배지 줄. `self-start`가 핵심이다. 부모가 `flex-col`이라 교차축 기본값이
        `stretch`이고, 그대로 두면 배지가 카드 전폭(1440에서 1148px)까지 늘어나
        상태 배지가 아니라 로딩 스켈레톤 바처럼 읽힌다(2026-09-10 Design Audit).
        배지는 항상 내용 폭이어야 한다.
      */}
      <div className="flex items-center justify-between gap-3">
        <span
          className={`inline-flex self-start rounded-full px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.1em] ${TONE_CLASSES[tone]}`}
        >
          {kind}
        </span>
        {meta !== undefined && (
          <span className="shrink-0 text-[12px] font-semibold text-brand-faint">{meta}</span>
        )}
      </div>
      {/*
        읽기 폭을 제한한다. 전폭 데이터 영역 안에서는 카드가 1450px까지 늘어나
        두 줄 문장이 화면을 가로질러 퍼졌다(2026-09-10 QA). 카드 배경은 영역을
        채우되 글은 한 눈에 읽히는 길이를 유지한다.
      */}
      <p className="mt-3 max-w-[64ch] text-[15px] font-[750] tracking-[-0.02em] text-brand-ink">
        {title}
      </p>
      <p className="mt-1.5 max-w-[64ch] text-[13px] leading-[1.6] text-brand-muted">
        {description}
      </p>
      {action !== undefined && <div className="mt-4">{action}</div>}
    </div>
  )
}
