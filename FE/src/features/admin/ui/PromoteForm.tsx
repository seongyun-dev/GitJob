import { useMemo, useState } from 'react'
import type {
  PromoteInput,
  TechnologyCandidate,
  TechnologyOption,
} from '@/features/admin/api/technologyCandidates'
import { useTechnologyOptions } from '@/features/admin/hooks/useTechnologyCandidates'
import { coordinateName } from '@/features/admin/ui/coordinateName'
import {
  deriveTechId,
  isValidTechId,
  JOB_DOMAINS,
  jobDomainLabel,
} from '@/features/admin/ui/deriveTechId'
import type { JobDomain } from '@/features/admin/ui/deriveTechId'

type Mode = 'link' | 'create'

/**
 * 승격 폼.
 *
 * <h2>승격은 대부분 "새 기술"이 아니다</h2>
 *
 * `@vue/tsconfig`와 `vue-tsc`는 둘 다 Vue.js다. 좌표 하나가 곧 기술 하나라고 보면
 * 같은 기술이 이름만 다르게 여러 개 등록되고, 프로필에는 사람이 읽을 수 없는
 * 빌드 플러그인 이름이 뜬다. 그래서 기본값은 **이미 등록된 기술에 좌표를 잇는 것**이고,
 * 새로 만드는 것은 따로 고르게 한다. 데이터 모델도 원래 이 모양이다 —
 * technology_mapping 이 자기 키를 가지고 technology 를 가리킨다.
 *
 * 기존 기술에 이을 때는 표시명·직무를 묻지 않는다. 그 값들은 기술을 등록할 때
 * 정해진 것이고, 나중에 붙는 좌표가 다시 쓰면 이미 자리잡은 기술의 이름이 바뀐다.
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
  // 폼이 열릴 때만 마운트되므로 마운트 자체가 조회 조건이다.
  const options = useTechnologyOptions(true)

  const [mode, setMode] = useState<Mode>('link')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const [techId, setTechId] = useState(() => deriveTechId(candidate.coordinate))
  const [displayName, setDisplayName] = useState(() =>
    coordinateName(candidate.ecosystem, candidate.coordinate),
  )
  const [domains, setDomains] = useState<JobDomain[]>([])
  const [note, setNote] = useState('')

  const all = useMemo(() => options.data ?? [], [options.data])
  const needle = query.trim().toLowerCase()
  /*
    입력하기 전에는 아무것도 내리지 않는다. 등록된 기술은 서른 개 가까이 되는데
    찾을 이름을 이미 알고 열는 화면이라, 목록을 펼쳐 두면 폼만 길어지고 스크롤이
    하나 더 생긴다. 대신 몇 개가 등록돼 있는지는 아래에 남긴다 — 빈 화면을 보고
    "등록된 게 없구나" 하고 새 기술로 넘어가면 중복이 생긴다.
  */
  const matched = useMemo(() => {
    if (needle === '') {
      return []
    }
    return all.filter(
      (option) =>
        option.techId.toLowerCase().includes(needle) ||
        option.displayName.toLowerCase().includes(needle),
    )
  }, [all, needle])

  const selectedOption = all.find((option) => option.techId === selected) ?? null
  const idError = isValidTechId(techId) ? null : '영소문자·숫자·하이픈만 쓸 수 있습니다.'
  const canSubmit =
    !pending && (mode === 'link' ? selected !== null : idError === null && domains.length > 0)

  function toggle(domain: JobDomain) {
    setDomains((current) =>
      current.includes(domain) ? current.filter((d) => d !== domain) : [...current, domain],
    )
  }

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (!canSubmit) {
          return
        }
        if (mode === 'link') {
          // 표시명·직무는 보내지 않는다. 서버는 이미 있는 기술이면 매핑만 더한다.
          onSubmit({
            candidateId: candidate.candidateId,
            techId: selected as string,
            note: note.trim() === '' ? undefined : note.trim(),
          })
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
      <div className="flex gap-2">
        <ModeTab active={mode === 'link'} onClick={() => setMode('link')}>
          기존 기술에 연결
        </ModeTab>
        <ModeTab active={mode === 'create'} onClick={() => setMode('create')}>
          새 기술로 등록
        </ModeTab>
      </div>

      {mode === 'link' && (
        <div>
          {/*
            고르면 그 이름이 입력칸에 들어가고 목록은 닫힌다. 반대로 글자를 고치면
            선택이 풀린다 — 입력칸에 "Vue.js"라고 적혀 있는데 실제로는 그 전에 고른
            다른 기술이 등록되는 상황을 만들지 않기 위해서다.
          */}
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setSelected(null)
              setListOpen(true)
            }}
            placeholder="기술 검색 (예: kafka, Vue)"
            className="w-full rounded-[10px] border border-brand-line px-3 py-2 text-[13px] outline-none placeholder:text-brand-faint focus:border-brand-400"
          />

          {options.isPending && (
            <p className="mt-2 text-[12.5px] text-brand-faint">등록된 기술을 불러오는 중…</p>
          )}
          {options.isError && (
            <p className="mt-2 text-[12.5px] text-tone-danger">
              기술 목록을 불러오지 못했습니다. 새 기술로 등록하려면 위 탭을 바꿔 주세요.
            </p>
          )}
          {options.isSuccess && needle === '' && (
            <p className="mt-2 text-[12.5px] text-brand-faint">
              {all.length === 0
                ? '등록된 기술이 없습니다. 새 기술로 등록해 주세요.'
                : `등록된 기술 ${all.length}개 · 이름 일부를 입력해 찾으세요`}
            </p>
          )}
          {options.isSuccess && listOpen && needle !== '' && matched.length === 0 && (
            <p className="mt-2 text-[12.5px] text-brand-faint">
              검색 결과가 없습니다. 등록된 적 없는 기술이면 새 기술로 등록해 주세요.
            </p>
          )}
          {listOpen && matched.length > 0 && (
            <ul className="mt-2 max-h-[168px] overflow-y-auto rounded-[10px] border border-brand-line">
              {matched.map((option) => (
                <li key={option.techId}>
                  <OptionRow
                    option={option}
                    selected={option.techId === selected}
                    onSelect={() => {
                      setSelected(option.techId)
                      setQuery(option.displayName)
                      setListOpen(false)
                    }}
                  />
                </li>
              ))}
            </ul>
          )}
          {/* 입력칸에는 표시명이 보이지만 실제로 등록되는 값은 식별자다. */}
          {selectedOption !== null && !listOpen && (
            <p className="mt-2 text-[12.5px] text-brand-600">
              선택됨 · <span className="font-evidence">{selectedOption.techId}</span>
            </p>
          )}
        </div>
      )}

      {mode === 'create' && (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="기술 식별자" error={idError}>
              <input
                className="w-full rounded-[10px] border border-brand-line px-3 py-2 font-evidence text-[13px] outline-none focus:border-brand-400"
                value={techId}
                onChange={(event) => setTechId(event.target.value)}
              />
            </Field>
            <Field label="표시명">
              <input
                className="w-full rounded-[10px] border border-brand-line px-3 py-2 text-[13px] outline-none focus:border-brand-400"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Field>
          </div>

          {/*
            직무는 기본값을 두지 않고 고르게 한다. 이 값이 프로필의 어느 칸에 들어갈지를
            정하는데, 서버가 기본 처리해 두면 잘못 들어간 것이 화면에 드러나지 않는다.
          */}
          <fieldset>
            <legend className="text-[11.5px] text-brand-faint">직무</legend>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1.5">
              {JOB_DOMAINS.map((domain) => (
                <label
                  key={domain}
                  className="inline-flex cursor-pointer items-center gap-1.5 text-[12.5px] text-brand-ink-soft"
                >
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
        </div>
      )}

      <Field label="메모 (선택)">
        <input
          className="w-full rounded-[10px] border border-brand-line px-3 py-2 text-[13px] outline-none placeholder:text-brand-faint focus:border-brand-400"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="왜 이렇게 판단했는지"
        />
      </Field>

      {/*
        등록될 내용은 고른 방식에 따라 다르므로 한 문장으로 뭉뚱그리지 않는다.
        아직 고르지 않았으면 아예 쓰지 않는다 — "고르면 보여 드립니다"는 자리만
        차지하고 아무것도 알려주지 않고, 그 상태에서는 버튼도 눌리지 않는다.
      */}
      {(mode === 'create' || selectedOption !== null) && (
        <p className="rounded-[10px] bg-[#F4F6FA] px-3 py-2 text-[12px] leading-[1.65] text-brand-muted">
          {mode === 'link' && selectedOption !== null ? (
            <>
              <span className="font-evidence">{candidate.coordinate}</span> 좌표가{' '}
              <b className="text-brand-ink">{selectedOption.displayName}</b>
              (으)로 해석됩니다. 새 기술은 만들어지지 않고 매핑만 더해집니다.
            </>
          ) : (
            <>
              새 기술 <span className="font-evidence">{techId}</span>가 초안에 등록되고,{' '}
              <span className="font-evidence">{candidate.coordinate}</span> 좌표에 정확히 일치하는
              매핑과 L0 규칙이 만들어집니다.
            </>
          )}{' '}
          초안에만 들어가고, 발행하기 전까지 사용자에게 보이는 결과는 바뀌지 않습니다.
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!canSubmit}
          className="flex-1 rounded-xl bg-linear-to-br from-brand-600 to-brand-400 px-4 py-2.5 text-[13.5px] font-bold text-white shadow-[0_10px_22px_rgba(47,94,235,0.22)] disabled:bg-none disabled:bg-brand-line disabled:text-brand-faint disabled:shadow-none"
        >
          {pending ? '처리 중…' : mode === 'link' ? '연결' : '새 기술로 등록'}
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

function ModeTab({
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
      className={`flex-1 rounded-[10px] border px-3 py-2 text-[12.5px] font-semibold transition-colors ${
        active
          ? 'border-brand-400 bg-tone-accent-bg text-brand-600'
          : 'border-brand-line bg-white text-brand-muted'
      }`}
    >
      {children}
    </button>
  )
}

/** 선택지 한 줄. 식별자는 실제로 등록될 값이므로 표시명과 함께 그대로 보여 준다. */
function OptionRow({
  option,
  selected,
  onSelect,
}: {
  option: TechnologyOption
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex w-full items-center justify-between gap-3 border-b border-brand-line px-3 py-2 text-left last:border-b-0 ${
        selected ? 'bg-tone-accent-bg' : 'bg-white'
      }`}
    >
      <span
        className={`truncate text-[13px] ${
          selected ? 'font-bold text-brand-600' : 'text-brand-ink'
        }`}
      >
        {option.displayName}
      </span>
      <span className="shrink-0 font-evidence text-[11.5px] text-brand-faint">{option.techId}</span>
    </button>
  )
}

function Field({
  label,
  error = null,
  children,
}: {
  label: string
  error?: string | null
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11.5px] text-brand-faint">{label}</span>
      {children}
      {error !== null && <span className="mt-1 block text-[11.5px] text-tone-danger">{error}</span>}
    </label>
  )
}
