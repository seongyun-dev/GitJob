import { useState } from 'react'
import type { ReactNode } from 'react'
import type { PromoteInput } from '@/features/admin/api/technologyCandidates'
import {
  decisionMessage,
  usePromoteCandidate,
  usePublishRegistry,
  useRegistryStatus,
  useRejectCandidate,
  useTechnologyCandidates,
} from '@/features/admin/hooks/useTechnologyCandidates'
import type {
  CandidateFilter,
  TechnologyCandidate,
} from '@/features/admin/hooks/useTechnologyCandidates'
import { CandidateDrawer } from '@/features/admin/ui/CandidateDrawer'
import { CandidateStatus } from '@/features/admin/ui/CandidateStatus'
import { coordinateName, hasSeparateCoordinate } from '@/features/admin/ui/coordinateName'
import { formatDay } from '@/features/admin/ui/formatDay'
import { PageHero } from '@/shared/ui/PageHero'

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
 *
 * <h2>시각 기준</h2>
 *
 * 같은 관리자 셸의 Monitoring 화면과 같은 어휘를 쓴다 — `PageHero`(eyebrow · 34px 제목),
 * 흰 카드(radius 18 · `brand-line` 테두리 · 부드러운 그림자), 브랜드 버튼. 이 화면만
 * 회색 구분선과 기본 버튼으로 남아 있어 같은 관리자 안에서 다른 제품처럼 보였다.
 */
const LIST_LIMIT = 50

const FILTERS: ReadonlyArray<{ value: CandidateFilter; label: string }> = [
  { value: 'UNDECIDED', label: '검토 대기' },
  { value: 'PROMOTED', label: '승격됨' },
  { value: 'REJECTED', label: '거절됨' },
  { value: 'ALL', label: '전체' },
]

export function TechnologyCandidatePage() {
  const [filter, setFilter] = useState<CandidateFilter>('UNDECIDED')
  const candidates = useTechnologyCandidates(LIST_LIMIT, filter)
  const registry = useRegistryStatus()
  const promote = usePromoteCandidate()
  const reject = useRejectCandidate()
  const publish = usePublishRegistry()

  /**
   * 드로어는 한 번에 하나만 연다. 후보 검토는 한 건을 끝까지 보고 결정하는 일이라
   * 여러 건을 동시에 펴 둘 이유가 없다.
   */
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [mode, setMode] = useState<'view' | 'promote' | 'reject'>('view')
  const [failedRow, setFailedRow] = useState<{ id: number; message: string } | null>(null)
  const [promoted, setPromoted] = useState<string | null>(null)

  function openDrawer(candidateId: number) {
    setFailedRow(null)
    setSelectedId(candidateId)
    setMode('view')
  }

  function closeDrawer() {
    setSelectedId(null)
    setMode('view')
  }

  function runPromote(input: PromoteInput) {
    setFailedRow(null)
    // 직전 승격의 성공 배너를 지운다. 남겨 두면 방금 실패한 결정 옆에
    // "등록했습니다"가 함께 떠서 어느 쪽이 이번 결과인지 알 수 없다.
    setPromoted(null)
    promote.mutate(input, {
      onSuccess: (result) => {
        closeDrawer()
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
        onSuccess: () => closeDrawer(),
        onError: (error) => setFailedRow({ id: candidateId, message: decisionMessage(error) }),
      },
    )
  }

  const draft = registry.data?.draft ?? null
  const rows = candidates.data ?? []
  const selected = rows.find((row) => row.candidateId === selectedId)

  return (
    <section className="py-8">
      <PageHero
        eyebrow="TECHNOLOGY REGISTRY"
        title="기술 후보 검토"
        description="분석에서 발견됐지만 레지스트리에 없는 의존성입니다. 최근 관찰된 순으로 보입니다."
        aside={
          <RegistryPanel
            current={registry.data?.current ?? null}
            draft={draft}
            publishing={publish.isPending}
            onPublish={() => publish.mutate()}
          />
        }
      />

      {publish.isError && <Banner tone="danger">{decisionMessage(publish.error)}</Banner>}
      {promoted !== null && (
        <Banner tone="success">
          <span className="font-evidence font-[750]">{promoted}</span> 을(를) 초안에 등록했습니다.
          발행해야 이후 분석에 반영됩니다.
        </Banner>
      )}

      {/* 목록을 카드 하나로 감싼다. 구분선만으로 나열하면 배경에 붙어 빈약해 보인다. */}
      <div className="mt-7 overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
        {/*
          기본은 미결정만이다. 결정이 끝난 것도 사용자 수로 정렬되므로 섞어 두면
          가장 많이 쓰이는 기술이 맨 위에 영구히 박히고 정작 볼 일이 아래로 밀린다.
          그렇다고 지우지는 않는다 — 거절에는 사유가 붙어 있고, 같은 좌표는 쓰는
          사람이 늘면서 다시 올라온다. 그때 그 사유를 읽을 수 있어야 한다.
        */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-brand-line px-6 py-4">
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map((option) => (
              <FilterTab
                key={option.value}
                active={filter === option.value}
                onClick={() => {
                  setFilter(option.value)
                  closeDrawer()
                }}
              >
                {option.label}
              </FilterTab>
            ))}
          </div>
          <p className="text-[12.5px] tabular-nums text-brand-faint">
            {candidates.isSuccess ? `${rows.length}건` : '—'}
          </p>
        </div>

        {candidates.isPending && (
          <p className="px-6 py-12 text-center text-[13.5px] text-brand-faint">불러오는 중…</p>
        )}
        {candidates.isError && (
          <p className="px-6 py-12 text-center text-[13.5px] text-tone-danger">
            {decisionMessage(candidates.error)}
          </p>
        )}
        {candidates.isSuccess && rows.length === 0 && (
          <div className="px-6 py-12 text-center">
            <p className="text-[15px] font-[750] text-brand-ink">
              {filter === 'UNDECIDED' ? '검토할 후보가 없습니다' : '해당하는 후보가 없습니다'}
            </p>
            <p className="mt-1.5 text-[13px] text-brand-faint">
              {filter === 'UNDECIDED'
                ? '분석이 새 의존성을 만나면 여기에 쌓입니다.'
                : '다른 묶음을 골라 보세요.'}
            </p>
          </div>
        )}

        <ul className="divide-y divide-brand-line">
          {rows.map((candidate) => (
            <li key={candidate.candidateId}>
              <CandidateRow
                candidate={candidate}
                selected={selectedId === candidate.candidateId}
                onOpen={() => openDrawer(candidate.candidateId)}
              />
            </li>
          ))}
        </ul>
      </div>

      {selected !== undefined && (
        <CandidateDrawer
          candidate={selected}
          mode={mode}
          promotePending={promote.isPending}
          rejectPending={reject.isPending}
          failedMessage={failedRow?.id === selected.candidateId ? failedRow.message : null}
          onModeChange={setMode}
          onPromote={runPromote}
          onReject={(note) => runReject(selected.candidateId, note)}
          onClose={closeDrawer}
        />
      )}
    </section>
  )
}

/** 결과 안내 띠. 성공·실패가 같은 자리·같은 모양이어야 어느 쪽인지 바로 읽힌다. */
function Banner({ tone, children }: { tone: 'success' | 'danger'; children: ReactNode }) {
  const toneClass =
    tone === 'success'
      ? 'bg-tone-success-bg text-tone-success'
      : 'bg-tone-danger-bg text-tone-danger'
  return (
    <p className={`mt-5 rounded-[12px] px-4 py-3 text-[13px] leading-[1.6] ${toneClass}`}>
      {children}
    </p>
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
    <div className="w-[260px] rounded-[18px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.12em] text-brand-faint">REGISTRY</p>

      <div className="mt-3 space-y-2.5">
        <VersionLine label="적용 중" value={current} tone="ink" />
        <VersionLine label="대기 초안" value={draft} tone={draft === null ? 'faint' : 'accent'} />
      </div>

      <button
        type="button"
        disabled={draft === null || publishing}
        onClick={onPublish}
        className="mt-4 w-full rounded-xl bg-linear-to-br from-brand-600 to-brand-400 px-4 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_22px_rgba(47,94,235,0.22)] transition-opacity disabled:from-brand-line disabled:to-brand-line disabled:text-brand-faint disabled:shadow-none"
      >
        {publishing ? '발행 중…' : '초안 발행'}
      </button>
    </div>
  )
}

function VersionLine({
  label,
  value,
  tone,
}: {
  label: string
  value: string | null
  tone: 'ink' | 'accent' | 'faint'
}) {
  const valueClass =
    tone === 'accent' ? 'text-brand-600' : tone === 'faint' ? 'text-brand-faint' : 'text-brand-ink'
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-[12px] text-brand-faint">{label}</span>
      <span className={`truncate font-evidence text-[12.5px] font-[750] ${valueClass}`}>
        {value ?? '없음'}
      </span>
    </div>
  )
}

/**
 * 한 후보의 근거.
 *
 * 사용자 수만 액센트로 둔다 — 결정이 그 값에 달려 있기 때문이다. 발생 횟수도 보여주지만
 * 강조하지 않는다(모노레포 하나가 그 숫자를 혼자 올릴 수 있다).
 *
 * 지표를 큰 숫자 블록이 아니라 인라인 칩으로 두는 이유: 값이 대부분 한 자리라 블록으로
 * 세우면 행이 비어 보이고, 좌표(왼쪽)와 지표(오른쪽)가 멀어져 시선이 끊긴다.
 *
 * 행을 펼친 동안에는 액션 버튼을 감춘다. 폼과 버튼이 함께 보이면 어느 것이 제출인지
 * 흐려진다.
 */
function CandidateRow({
  candidate,
  selected,
  onOpen,
}: {
  candidate: TechnologyCandidate
  selected: boolean
  onOpen: () => void
}) {
  const name = coordinateName(candidate.ecosystem, candidate.coordinate)
  const showCoordinate = hasSeparateCoordinate(candidate.ecosystem, candidate.coordinate)

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-expanded={selected}
      className={`flex w-full flex-wrap items-center justify-between gap-x-6 gap-y-2 px-6 py-4 text-left transition-colors ${
        selected ? 'bg-tone-accent-bg' : 'hover:bg-[#F8FAFD]'
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-evidence text-[15px] font-[750] text-brand-ink">
            {name}
          </span>
          <CandidateStatus status={candidate.status} />
        </div>
        {showCoordinate && (
          <p className="mt-0.5 truncate font-evidence text-[12px] text-brand-faint">
            {candidate.coordinate}
          </p>
        )}

        {/* 생태계는 칩으로 둔다. 좌표를 읽기 전에 어느 생태계인지가 먼저 걸린다. */}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Chip>{candidate.ecosystem}</Chip>
          {candidate.scope !== null && (
            <span className="text-[12px] text-brand-muted">· {candidate.scope}</span>
          )}
        </div>

        {/*
          기간은 따로 한 줄. 지난주에 처음 나타난 것과 반년째 쌓이는 것은 같은
          후보가 아니고, 목록도 최근 관찰 순으로 줄 세운다.
        */}
        <p className="mt-1.5 text-[12px] tabular-nums text-brand-faint">
          {`처음 ${formatDay(candidate.firstSeenAt)} · 최근 ${formatDay(candidate.lastSeenAt)}`}
        </p>

        {/* 사용자 수만 액센트다. 선언 수는 모노레포 하나가 혼자 올린다. */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Chip emphasis>사용자 {candidate.distinctUserCount}</Chip>
          <Chip>저장소 {candidate.distinctRepositoryCount}</Chip>
          <Chip>선언 {candidate.occurrenceCount}</Chip>
        </div>
      </div>

      <span className="shrink-0 text-[12.5px] font-semibold text-brand-600">검토 →</span>
    </button>
  )
}

/** 목록이 보여 줄 묶음을 고르는 칩. */
function FilterTab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
        active
          ? 'bg-brand-600 text-white'
          : 'bg-[#F4F6FA] text-brand-muted hover:text-brand-ink'
      }`}
    >
      {children}
    </button>
  )
}

/** 한 조각짜리 표식. 칩은 숫자와 생태계처럼 짧고 눈에 먼저 걸려야 하는 값만 담는다. */
function Chip({ children, emphasis = false }: { children: ReactNode; emphasis?: boolean }) {
  const toneClass = emphasis
    ? 'bg-tone-accent-bg font-[750] text-brand-600'
    : 'bg-[#F4F6FA] text-brand-muted'
  return (
    <span
      className={`inline-flex items-center rounded-[7px] px-2 py-1 text-[11.5px] tabular-nums ${toneClass}`}
    >
      {children}
    </span>
  )
}
