import { useEffect } from 'react'
import type { PromoteInput } from '@/features/admin/api/technologyCandidates'
import { useCandidateDetail } from '@/features/admin/hooks/useTechnologyCandidates'
import type { TechnologyCandidate } from '@/features/admin/hooks/useTechnologyCandidates'
import { decisionMessage } from '@/features/admin/hooks/useTechnologyCandidates'
import { CandidateStatus } from '@/features/admin/ui/CandidateStatus'
import { coordinateName, hasSeparateCoordinate } from '@/features/admin/ui/coordinateName'
import { formatDay } from '@/features/admin/ui/formatDay'
import { PromoteForm } from '@/features/admin/ui/PromoteForm'
import { RejectForm } from '@/features/admin/ui/RejectForm'

/**
 * 후보 하나를 판단하는 자리 · 우측 드로어.
 *
 * <h2>왜 인라인 확장이 아니라 드로어인가</h2>
 *
 * 실제 후보는 수십 건이 아니라 몇 건이다. 목록을 빠르게 쳐내는 화면이 아니라 한 건을
 * 신중히 보는 화면이라는 뜻이다. 인라인으로 펴면 폼이 열릴 때마다 아래 행이 밀려
 * 목록이 출렁이고, 근거를 함께 보여줄 자리도 나오지 않는다. 드로어는 목록을 그대로
 * 둔 채 판단에 필요한 것(합계·근거·폼)을 한 화면에 모은다.
 *
 * <h2>근거를 여기서 읽는 이유</h2>
 *
 * 목록이 주는 것은 합계(사용자·저장소·선언)뿐이다. 그 숫자가 어디서 나왔는지 모르면
 * 승격·거절을 눈감고 누르게 된다. 드로어가 열릴 때만 상세를 조회한다.
 */
export function CandidateDrawer({
  candidate,
  mode,
  promotePending,
  rejectPending,
  failedMessage,
  onModeChange,
  onPromote,
  onReject,
  onClose,
}: {
  candidate: TechnologyCandidate
  mode: 'view' | 'promote' | 'reject'
  promotePending: boolean
  rejectPending: boolean
  failedMessage: string | null
  onModeChange: (mode: 'view' | 'promote' | 'reject') => void
  onPromote: (input: PromoteInput) => void
  onReject: (note: string) => void
  onClose: () => void
}) {
  const detail = useCandidateDetail(candidate.candidateId)

  // Escape 로 닫는다. 폼이 열려 있어도 마찬가지다 — 제출하지 않고 빠져나오는 길이
  // 항상 있어야 한다.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const name = coordinateName(candidate.ecosystem, candidate.coordinate)
  const showCoordinate = hasSeparateCoordinate(candidate.ecosystem, candidate.coordinate)

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      {/* 바깥을 눌러도 닫힌다. 판단을 강요하지 않는다. */}
      <button
        type="button"
        aria-label="닫기"
        onClick={onClose}
        className="flex-1 cursor-default bg-[rgba(16,26,46,0.32)]"
      />

      <aside
        role="dialog"
        aria-label={`${name} 후보 검토`}
        className="flex h-full w-full max-w-[520px] flex-col overflow-y-auto bg-white shadow-[-12px_0_32px_rgba(25,47,81,0.16)]"
      >
        <header className="sticky top-0 z-10 border-b border-brand-line bg-white px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate font-evidence text-[18px] font-[750] text-brand-ink">
                  {name}
                </h2>
                <CandidateStatus status={candidate.status} />
              </div>
              {showCoordinate && (
                <p className="mt-1 truncate font-evidence text-[12px] text-brand-faint">
                  {candidate.coordinate}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="shrink-0 rounded-lg px-2 py-1 text-[18px] leading-none text-brand-faint transition-colors hover:text-brand-ink"
            >
              ✕
            </button>
          </div>
        </header>

        <div className="flex-1 px-6 py-5">
          <Section title="집계">
            <div className="grid grid-cols-3 gap-2">
              <Metric label="사용자" value={candidate.distinctUserCount} emphasis />
              <Metric label="저장소" value={candidate.distinctRepositoryCount} />
              <Metric label="선언" value={candidate.occurrenceCount} />
            </div>
            <p className="mt-3 text-[12px] text-brand-faint">
              {`${candidate.ecosystem}${candidate.scope !== null ? ` · ${candidate.scope}` : ''} · 처음 ${formatDay(candidate.firstSeenAt)} · 최근 ${formatDay(candidate.lastSeenAt)}`}
            </p>
          </Section>

          <Section title="근거">
            {detail.isPending && (
              <p className="text-[13px] text-brand-faint">근거를 불러오는 중…</p>
            )}
            {detail.isError && (
              <p className="text-[13px] text-tone-danger">{decisionMessage(detail.error)}</p>
            )}
            {detail.isSuccess && detail.data.observations.length === 0 && (
              <p className="text-[13px] text-brand-faint">기록된 관찰이 없습니다.</p>
            )}
            {detail.isSuccess && detail.data.observations.length > 0 && (
              <ul className="overflow-hidden rounded-[12px] border border-brand-line">
                {detail.data.observations.map((observation, index) => (
                  <li
                    key={`${observation.repositoryId}-${index}`}
                    className="flex items-center justify-between gap-3 border-b border-brand-line px-3.5 py-2.5 last:border-b-0"
                  >
                    <div className="min-w-0">
                      {/*
                        저장소 이름은 응답에 없다. 그럴듯한 이름을 만들지 않고 식별자를
                        그대로 둔다 — 잘못된 이름이 판단의 근거가 되는 것이 더 나쁘다.
                      */}
                      <p className="truncate font-evidence text-[12.5px] text-brand-ink-soft">
                        저장소 #{observation.repositoryId}
                      </p>
                      <p className="mt-0.5 text-[11.5px] text-brand-faint">
                        {`${observation.scope ?? 'scope 미상'} · ${formatDay(observation.observedAt)}`}
                      </p>
                    </div>
                    <span className="shrink-0 text-[12px] tabular-nums text-brand-muted">
                      {observation.occurrenceCount}건
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {detail.isSuccess && detail.data.decidedAt !== null && (
            <Section title="결정 이력">
              <p className="text-[13px] text-brand-ink-soft">
                {detail.data.promotedTechId !== null
                  ? `${formatDay(detail.data.decidedAt)} 승격 · ${detail.data.promotedTechId}`
                  : `${formatDay(detail.data.decidedAt)} 거절`}
              </p>
              {detail.data.decisionNote !== null && detail.data.decisionNote !== '' && (
                <p className="mt-1.5 text-[12.5px] leading-[1.6] text-brand-muted">
                  {detail.data.decisionNote}
                </p>
              )}
            </Section>
          )}

          {failedMessage !== null && (
            <p className="mt-4 rounded-[10px] bg-tone-danger-bg px-3 py-2 text-[12.5px] text-tone-danger">
              {failedMessage}
            </p>
          )}
        </div>

        <footer className="sticky bottom-0 border-t border-brand-line bg-white px-6 py-4">
          {mode === 'view' && (
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onModeChange('promote')}
                className="flex-1 rounded-xl bg-linear-to-br from-brand-600 to-brand-400 px-4 py-2.5 text-[13.5px] font-bold text-white shadow-[0_10px_22px_rgba(47,94,235,0.22)]"
              >
                승격
              </button>
              <button
                type="button"
                onClick={() => onModeChange('reject')}
                className="rounded-xl border border-brand-line bg-white px-5 py-2.5 text-[13.5px] font-semibold text-brand-muted transition-colors hover:text-tone-danger"
              >
                거절
              </button>
            </div>
          )}

          {mode === 'promote' && (
            <PromoteForm
              candidate={candidate}
              pending={promotePending}
              onSubmit={onPromote}
              onCancel={() => onModeChange('view')}
            />
          )}
          {mode === 'reject' && (
            <RejectForm
              pending={rejectPending}
              onSubmit={onReject}
              onCancel={() => onModeChange('view')}
            />
          )}
        </footer>
      </aside>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-1 mb-6 last:mb-0">
      <p className="mb-2.5 text-[11px] font-extrabold tracking-[0.12em] text-brand-faint">
        {title}
      </p>
      {children}
    </section>
  )
}

/** 집계 한 칸. 결정 근거인 사용자 수만 액센트다. */
function Metric({
  label,
  value,
  emphasis = false,
}: {
  label: string
  value: number
  emphasis?: boolean
}) {
  return (
    <div className={`rounded-[12px] px-3 py-2.5 ${emphasis ? 'bg-tone-accent-bg' : 'bg-[#F4F6FA]'}`}>
      <p className="text-[11.5px] text-brand-faint">{label}</p>
      <p
        className={`mt-0.5 text-[20px] font-[750] tabular-nums ${
          emphasis ? 'text-brand-600' : 'text-brand-ink'
        }`}
      >
        {value.toLocaleString('ko-KR')}
      </p>
    </div>
  )
}
