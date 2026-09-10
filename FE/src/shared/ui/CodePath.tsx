import type { ReactNode } from 'react'

/**
 * 코드 위치 표기 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`가 파일 경로를 고정폭 칩으로 놓는다(`KafkaConfig.java:24`).
 * 이 제품에서 근거는 "어느 파일 몇 번째 줄"이라 경로가 본문 글자와 섞이면 안 된다.
 * 고정폭 대비는 `index.css`의 `--font-evidence`가 이미 갖고 있는 시각 시그니처다.
 *
 * 링크가 아니다. GitHub Permalink로 여는 것은 `EvidenceRow`가 맡는다.
 */
export function CodePath({ children }: { children: ReactNode }) {
  return (
    <code className="inline-block rounded-md border border-[#E8EDF4] bg-[#F5F7FA] px-2 py-[3px] font-evidence text-[12.5px] break-all text-brand-ink-soft">
      {children}
    </code>
  )
}

/**
 * Evidence 유형 칩(`DEP` · `CFG` · `IMPL`).
 *
 * 값 목록을 닫지 않는다. 유형은 C조 판정 결과가 주는 값이고 FE가 정하지 않는다.
 * 다만 표기 형태는 고정한다.
 */
export function EvidenceKind({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-tone-accent-bg px-2 py-1 font-evidence text-[11px] font-extrabold tracking-[0.04em] text-tone-accent">
      {children}
    </span>
  )
}
