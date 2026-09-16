import { useState } from 'react'

/**
 * 거절 폼.
 *
 * 사유를 필수로 받는다. 후보는 지워지지 않고 관찰 수만 계속 늘어나므로, 세
 * 명이 쓸 때 거절한 것이 삼백 명이 쓸 때 다시 목록에 떠오른다. 그때 왜
 * 거절했는지 적혀 있지 않으면 다음 사람이 같은 판단을 처음부터 다시 한다.
 */
export function RejectForm({
  pending,
  onSubmit,
  onCancel,
}: {
  pending: boolean
  onSubmit: (note: string) => void
  onCancel: () => void
}) {
  const [note, setNote] = useState('')
  const canSubmit = note.trim() !== '' && !pending

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) {
          onSubmit(note.trim())
        }
      }}
    >
      <label className="block">
        <span className="mb-1 block text-[11.5px] text-brand-faint">거절 사유</span>
        <input
          className="w-full rounded-[10px] border border-brand-line px-3 py-2 text-[13px] outline-none placeholder:text-brand-faint focus:border-brand-400"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="예: 라이브러리가 아니라 빌드 도구"
        />
      </label>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!canSubmit}
          className="flex-1 rounded-xl bg-tone-danger px-4 py-2.5 text-[13.5px] font-bold text-white disabled:bg-brand-line disabled:text-brand-faint"
        >
          {pending ? '처리 중…' : '거절'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-brand-line bg-white px-5 py-2.5 text-[13.5px] font-semibold text-brand-muted"
        >
          취소
        </button>
      </div>
    </form>
  )
}
