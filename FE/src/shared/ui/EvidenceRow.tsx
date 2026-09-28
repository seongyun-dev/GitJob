/**
 * 근거 행. 저장소명 · 파일경로:라인을 고정폭으로 표시한다.
 *
 * **permalink가 없으면 null을 반환한다.** 근거 없는 판정 행을 보여주지 않는다는
 * 와이어프레임 1-1 금지 규칙 4를 렌더 단계에서 강제하는 것이 목적이다.
 * 리스트에서 걸러내는 것을 잊어도 화면에 새어 나가지 않는다.
 *
 * 고정폭 대비는 와이어프레임 1-2가 "이 제품의 시각적 시그니처"로 규정했다.
 * 서체 대비를 임의로 낮추지 않는다.
 */
export function EvidenceRow({
  repo,
  filePath,
  lineStart,
  lineEnd,
  permalink,
}: {
  repo: string
  filePath: string
  lineStart: number
  lineEnd?: number
  permalink: string | null
}) {
  if (!permalink) {
    return null
  }

  const lines = lineEnd === undefined ? `${lineStart}` : `${lineStart}-${lineEnd}`

  return (
    <a
      href={permalink}
      target="_blank"
      rel="noreferrer"
      className="block font-evidence text-xs text-tone-neutral hover:text-tone-accent"
    >
      <span>{repo}</span>
      <span aria-hidden="true"> / </span>
      <span>
        {filePath}:{lines}
      </span>
    </a>
  )
}
