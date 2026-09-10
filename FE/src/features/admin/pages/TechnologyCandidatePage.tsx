import { useState } from 'react'
import type { PromoteInput } from '@/features/admin/api/technologyCandidates'
import {
  decisionMessage,
  usePromoteCandidate,
  usePublishRegistry,
  useRegistryStatus,
  useRejectCandidate,
  useTechnologyCandidates,
} from '@/features/admin/hooks/useTechnologyCandidates'
import type { TechnologyCandidate } from '@/features/admin/hooks/useTechnologyCandidates'
import { PromoteForm } from '@/features/admin/ui/PromoteForm'
import { RejectForm } from '@/features/admin/ui/RejectForm'
import { CountStat } from '@/shared/ui/CountStat'

/**
 * 기술 후보 검토 화면 · 티켓 S15P21E102-14.
 *
 * <h2>이 화면이 있는 이유</h2>
 *
 * 분석 워커는 매니페스트에서 본 의존성 중 레지스트리에 없는 것을 후보로 남긴다.
 * 그 목록을 사람이 보고 "이건 기술로 등록한다 / 이건 아니다"를 정하는 자리가
 * 여기다. 자동 등록하지 않는 이유는 좌표 하나가 곧 기술이 아니기 때문이다 —
 * 빌드 플러그인, 사내 라이브러리, 예제 코드가 같은 모양으로 올라온다.
 *
 * <h2>왜 바로 반영되지 않는가</h2>
 *
 * 승격은 초안 버전에 쌓이고, 발행은 따로 누른다. 판정이 끝난 분석은 자기가 쓴
 * 레지스트리 버전을 가리키고 있어서, 발행 전까지 사용자 화면은 그대로다.
 * 한 주치 결정을 버전 하나로 내보내는 것도 같은 구조 덕분이다.
 */
const LIST_LIMIT = 50

export function TechnologyCandidatePage() {
  const candidates = useTechnologyCandidates(LIST_LIMIT)
  const registry = useRegistryStatus()
  const promote = usePromoteCandidate()
  const reject = useRejectCandidate()
  const publish = usePublishRegistry()

  /** 한 번에 한 행만 편다. 둘을 동시에 열면 어느 폼을 제출했는지 흐려진다. */
  const [openRow, setOpenRow] = useState<{ id: number; mode: 'promote' | 'reject' } | null>(null)
  const [failedRow, setFailedRow] = useState<{ id: number; message: string } | null>(null)
  const [promoted, setPromoted] = useState<string | null>(null)

  function runPromote(input: PromoteInput) {
    setFailedRow(null)
    // 직전 승격의 성공 배너를 지운다. 남겨 두면 방금 실패한 결정 옆에
    // "등록했습니다"가 함께 떠서 어느 쪽이 이번 결과인지 알 수 없다.
    setPromoted(null)
    promote.mutate(input, {
      onSuccess: (result) => {
        setOpenRow(null)
        setPromoted(result.techId)
      },
      onError: (error) =>
        setFailedRow({ id: input.candidateId, message: decisionMessage(error) }),
    })
  }

  function runReject(candidateId: number, note: string) {
    setFailedRow(null)
    setPromoted(null)
    reject.mutate(
      { candidateId, note },
      {
        onSuccess: () => setOpenRow(null),
        onError: (error) => setFailedRow({ id: candidateId, message: decisionMessage(error) }),
      },
    )
  }

  const draft = registry.data?.draft ?? null
  const rows = candidates.data ?? []

  return (
    <section className="py-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">기술 후보 검토</h1>
          <p className="mt-1 text-sm text-tone-neutral">
            분석에서 발견됐지만 레지스트리에 없는 의존성입니다. 사용자가 많은 순으로 보입니다.
          </p>
        </div>
        <RegistryPanel
          current={registry.data?.current ?? null}
          draft={draft}
          publishing={publish.isPending}
          onPublish={() => publish.mutate()}
        />
      </header>

      {publish.isError && (
        <p className="mt-3 rounded bg-tone-danger-bg px-3 py-2 text-sm text-tone-danger">
          {decisionMessage(publish.error)}
        </p>
      )}
      {promoted !== null && (
        <p className="mt-3 rounded bg-tone-success-bg px-3 py-2 text-sm text-tone-success">
          <span className="font-evidence">{promoted}</span> 을(를) 초안에 등록했습니다. 발행해야
          이후 분석에 반영됩니다.
        </p>
      )}

      {candidates.isPending && <p className="mt-8 text-sm text-tone-neutral">불러오는 중…</p>}
      {candidates.isError && (
        <p className="mt-8 text-sm text-tone-danger">{decisionMessage(candidates.error)}</p>
      )}
      {candidates.isSuccess && rows.length === 0 && (
        <p className="mt-8 text-sm text-tone-neutral">
          검토할 후보가 없습니다. 분석이 새 의존성을 만나면 여기에 쌓입니다.
        </p>
      )}

      <ul className="mt-6 divide-y divide-neutral-200">
        {rows.map((candidate) => (
          <li key={candidate.candidateId} className="py-4">
            <CandidateRow candidate={candidate} />

            {failedRow?.id === candidate.candidateId && (
              <p className="mt-2 text-sm text-tone-danger">{failedRow.message}</p>
            )}

            {openRow?.id === candidate.candidateId && openRow.mode === 'promote' && (
              <PromoteForm
                candidate={candidate}
                pending={promote.isPending}
                onSubmit={runPromote}
                onCancel={() => setOpenRow(null)}
              />
            )}
            {openRow?.id === candidate.candidateId && openRow.mode === 'reject' && (
              <RejectForm
                pending={reject.isPending}
                onSubmit={(note) => runReject(candidate.candidateId, note)}
                onCancel={() => setOpenRow(null)}
              />
            )}
            {openRow?.id !== candidate.candidateId && (
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  className="rounded border border-neutral-300 px-3 py-1 text-sm"
                  onClick={() => setOpenRow({ id: candidate.candidateId, mode: 'promote' })}
                >
                  승격
                </button>
                <button
                  type="button"
                  className="rounded border border-neutral-300 px-3 py-1 text-sm text-tone-danger"
                  onClick={() => setOpenRow({ id: candidate.candidateId, mode: 'reject' })}
                >
                  거절
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * 지금 판정에 쓰이는 버전과 대기 중인 초안.
 *
 * 초안이 없으면 발행 버튼을 비활성화한다. 누를 수 있게 두면 "발행할 초안이
 * 없습니다" 오류를 받는 것이 유일한 결과다.
 */
function RegistryPanel({
  current,
  draft,
  publishing,
  onPublish,
}: {
  current: string | null
  draft: string | null
  publishing: boolean
  onPublish: () => void
}) {
  return (
    <div className="rounded-md border border-neutral-200 px-4 py-3 text-sm">
      <p className="text-xs text-tone-neutral">적용 중인 레지스트리</p>
      <p className="font-evidence">{current ?? '없음'}</p>
      <p className="mt-2 text-xs text-tone-neutral">대기 중인 초안</p>
      <p className="font-evidence">{draft ?? '없음'}</p>
      <button
        type="button"
        disabled={draft === null || publishing}
        onClick={onPublish}
        className="mt-3 w-full rounded bg-neutral-900 px-3 py-1 text-sm text-white disabled:bg-neutral-300"
      >
        {publishing ? '발행 중…' : '초안 발행'}
      </button>
    </div>
  )
}

/**
 * 한 후보의 근거.
 *
 * 사용자 수를 액센트로 둔 것은 결정이 그 값에 달려 있기 때문이다. 발생 횟수도
 * 보여주지만 강조하지 않는다 — 모노레포 하나가 그 숫자를 혼자 올릴 수 있다.
 */
function CandidateRow({ candidate }: { candidate: TechnologyCandidate }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="truncate font-evidence text-sm">{candidate.coordinate}</p>
        <p className="mt-1 text-xs text-tone-neutral">
          {candidate.ecosystem}
          {candidate.scope !== null && ` · ${candidate.scope}`}
          {` · 처음 ${formatDay(candidate.firstSeenAt)}`}
          {` · 최근 ${formatDay(candidate.lastSeenAt)}`}
        </p>
      </div>
      <div className="flex shrink-0 gap-6">
        <CountStat label="사용자" value={candidate.distinctUserCount} unit="명" emphasis="accent" />
        <CountStat label="저장소" value={candidate.distinctRepositoryCount} unit="개" />
        <CountStat label="선언" value={candidate.occurrenceCount} unit="건" />
      </div>
    </div>
  )
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  })
}
