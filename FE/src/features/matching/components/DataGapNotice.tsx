import { summarizeDataGaps } from '@/features/matching/model/presentation'

/** 내부 진단 코드 대신 사용자가 판단에 필요한 한계만 보여준다. */
export function DataGapNotice({
  gaps,
  className = '',
}: {
  gaps: readonly string[]
  className?: string
}) {
  const messages = summarizeDataGaps(gaps)
  if (messages.length === 0) {
    return null
  }

  return (
    <ul
      className={`grid gap-1.5 rounded-[14px] border border-brand-line bg-white/70 px-4 py-3 ${className}`}
    >
      {messages.map((message) => (
        <li key={message} className="text-[11.5px] leading-[1.6] text-tone-neutral">
          · {message}
        </li>
      ))}
    </ul>
  )
}
