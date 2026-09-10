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
      className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-neutral-200 bg-neutral-50 p-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) {
          onSubmit(note.trim())
        }
      }}
    >
      <input
        className="min-w-60 flex-1 rounded border border-neutral-300 px-2 py-1 text-sm"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="거절 사유 (예: 라이브러리가 아니라 빌드 도구)"
      />
      <button
        type="submit"
        disabled={!canSubmit}
        className="rounded bg-tone-danger px-3 py-1 text-sm text-white disabled:bg-neutral-300"
      >
        {pending ? '처리 중…' : '거절'}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="rounded border border-neutral-300 px-3 py-1 text-sm"
      >
        취소
      </button>
    </form>
  )
}
