/**
 * 진입 인트로가 쓰는 아이콘 · 티켓 S15P21E102-213 (Landing Redesign 교체분).
 *
 * 확정 디자인이 lucide 계열 선 아이콘을 인라인 SVG로 갖고 있어 그대로 옮겼다. 아이콘
 * 패키지를 새로 들이지 않은 것은 여기서 쓰는 것이 일곱 개뿐이고, 인트로는 첫 진입에
 * 한 번 재생되고 마는 화면이라 번들에 라이브러리를 하나 더 얹을 자리가 아니기 때문이다.
 *
 * 크기와 색은 props로 받지 않는다. `width`/`height`는 `className`의 Tailwind 크기가,
 * 선 색은 `stroke="currentColor"`가 부모의 `text-*`를 따라간다. 장면마다 흰 선과
 * 파란 선을 오가는데 색을 props로 받으면 호출부가 전부 색 문자열을 들고 있게 된다.
 */

type IconProps = { className?: string }

const STROKE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

export function GithubIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...STROKE}>
      <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
      <path d="M9 18c-4.51 2-5-2-7-2" />
    </svg>
  )
}

/** 판정 오브. GitJob이 근거를 찾는 일 자체를 가리킨다. */
export function SearchIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...STROKE}>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  )
}

/** 쌓인 근거. `나의 경험`·`현재 경험`이 같은 아이콘을 쓴다. */
export function LayersIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...STROKE}>
      <path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z" />
      <path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65" />
      <path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65" />
    </svg>
  )
}

/** 채용 기회. 흐름의 끝과 공고 카드가 같은 아이콘을 쓴다. */
export function BriefcaseIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...STROKE}>
      <rect width="20" height="14" x="2" y="7" rx="2" ry="2" />
      <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
    </svg>
  )
}

/** 저장소. 읽어 들이는 대상이 폴더가 아니라 Git 저장소라는 것이 드러나야 한다. */
export function RepoIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...STROKE}>
      <path d="M9 20H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v5" />
      <circle cx="13" cy="12" r="2" />
      <path d="M18 19c-2.8 0-5-2.2-5-5v8" />
      <circle cx="20" cy="19" r="2" />
    </svg>
  )
}

/** 더 채우면 열리는 쪽. 위로 향하는 화살표가 `부족분을 채운다`를 가리킨다. */
export function ArrowUpIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...STROKE}>
      <path d="M12 3v18" />
      <path d="m19 10-7-7-7 7" />
      <path d="M5 21h14" />
    </svg>
  )
}

/** 다음 방향. 추천이 점수가 아니라 방향이라는 것을 나침반이 말한다. */
export function CompassIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...STROKE}>
      <circle cx="12" cy="12" r="10" />
      <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
    </svg>
  )
}
