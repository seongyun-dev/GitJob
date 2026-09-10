import { useState } from 'react'
import type { PromoteInput, TechnologyCandidate } from '@/features/admin/api/technologyCandidates'
import {
  deriveTechId,
  isValidTechId,
  JOB_DOMAINS,
  jobDomainLabel,
} from '@/features/admin/ui/deriveTechId'
import type { JobDomain } from '@/features/admin/ui/deriveTechId'

/**
 * 승격 폼.
 *
 * 식별자와 표시명은 좌표에서 미리 채워 둔다. 좌표가 곧 답인 경우가 대부분이라
 * 스무 건을 처리하는 관리자가 같은 문자열을 스무 번 옮겨 적게 하지 않는다.
 *
 * 직무는 기본값을 두지 않고 고르게 한다. 이 값이 프로필의 어느 칸에 들어갈지를
 * 정하는데, 백엔드로 기본 처리해 두면 잘못 들어간 것이 화면에서 드러나지 않는다.
 */
export function PromoteForm({
  candidate,
  pending,
  onSubmit,
  onCancel,
}: {
  candidate: TechnologyCandidate
  pending: boolean
  onSubmit: (input: PromoteInput) => void
  onCancel: () => void
}) {
  const derived = deriveTechId(candidate.coordinate)
  const [techId, setTechId] = useState(derived)
  const [displayName, setDisplayName] = useState(candidate.coordinate)
  const [domains, setDomains] = useState<JobDomain[]>([])
  const [note, setNote] = useState('')

  const idError = isValidTechId(techId) ? null : '영소문자·숫자·하이픈만 쓸 수 있습니다.'
  const canSubmit = idError === null && domains.length > 0 && !pending

  function toggle(domain: JobDomain) {
    setDomains((current) =>
      current.includes(domain) ? current.filter((d) => d !== domain) : [...current, domain],
    )
  }

  return (
    <form
      className="mt-3 space-y-3 rounded-md border border-neutral-200 bg-neutral-50 p-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (!canSubmit) {
          return
        }
        onSubmit({
          candidateId: candidate.candidateId,
          techId,
          displayName: displayName.trim(),
          jobDomains: domains,
          note: note.trim() === '' ? undefined : note.trim(),
        })
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs">
          <span className="text-tone-neutral">기술 식별자</span>
          <input
            className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 font-evidence text-sm"
            value={techId}
            onChange={(event) => setTechId(event.target.value)}
          />
          {idError !== null && <span className="mt-1 block text-tone-danger">{idError}</span>}
        </label>
        <label className="block text-xs">
          <span className="text-tone-neutral">표시명</span>
          <input
            className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
      </div>

      <fieldset className="text-xs">
        <legend className="text-tone-neutral">직무</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {JOB_DOMAINS.map((domain) => (
            <label key={domain} className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={domains.includes(domain)}
                onChange={() => toggle(domain)}
              />
              {jobDomainLabel(domain)}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="block text-xs">
        <span className="text-tone-neutral">메모 (선택)</span>
        <input
          className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="왜 등록하는지"
        />
      </label>

      <p className="text-xs text-tone-neutral">
        {candidate.ecosystem} 생태계의 <span className="font-evidence">{candidate.coordinate}</span>{' '}
        좌표에 정확히 일치하는 매핑과 L0 규칙이 만들어집니다. 초안에만 들어가고, 발행하기 전까지
        사용자에게 보이는 결과는 바뀌지 않습니다.
      </p>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded bg-neutral-900 px-3 py-1 text-sm text-white disabled:bg-neutral-300"
        >
          {pending ? '등록 중…' : '초안에 등록'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-neutral-300 px-3 py-1 text-sm"
        >
          취소
        </button>
      </div>
    </form>
  )
}
