import type { BranchSummary } from '@/features/analysis/api/types'
import { ApiError } from '@/shared/api/client'

/**
 * 브랜치 선택 · 티켓 S15P21E102-117.
 *
 * 브랜치는 선택 사항이 아니라 필수다. `POST /analyses`가 `branchName`을 요구하고
 * 서버가 그 브랜치의 tip commit으로 분석 대상을 고정한다(BE `AnalysisCreateRequest`).
 *
 * 조회는 이 컴포넌트가 하지 않는다. 저장소별 카드가 받아 내려준다.
 * `commitSha`는 조회 시점 값이고 요청에 싣지 않으므로 참고 표시로만 쓴다.
 *
 * `inputId`를 받는 이유: 선택한 저장소마다 이 컴포넌트가 하나씩 렌더되므로
 * id를 고정하면 문서에 중복 id가 생기고 label이 첫 번째 select만 가리킨다.
 *
 * 로딩·빈 목록·오류를 `QueryStatePanel`로 그리지 않는다. 그 패널은 페이지 폭을
 * 전제한 카드라 380px 분석 범위 패널 안에서는 과하게 크다. 여기서는 한 줄짜리
 * 상태만 두고, 재시도 버튼도 카드 크기에 맞춘 작은 형태로 둔다.
 */

const LABEL = 'block text-[11px] font-bold tracking-[0.1em] text-brand-faint uppercase'

export function BranchPicker({
  inputId,
  branches,
  value,
  onChange,
  isLoading,
  error,
  onRetry,
}: {
  inputId: string
  branches: BranchSummary[] | undefined
  value: string
  onChange: (branch: string) => void
  isLoading: boolean
  error: unknown
  onRetry: () => void
}) {
  if (isLoading) {
    return (
      <p className="text-[12px] text-brand-faint" role="status" aria-live="polite">
        브랜치를 불러오는 중입니다…
      </p>
    )
  }

  if (error !== null) {
    return (
      <div role="alert">
        <p className="text-[11.5px] leading-[1.5] text-tone-danger">
          {error instanceof ApiError
            ? `브랜치를 불러오지 못했습니다. ${error.message} (코드 ${error.code})`
            : '브랜치를 불러오지 못했습니다.'}
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-1.5 rounded-lg border border-neutral-300 px-2.5 py-1 text-[11.5px] font-semibold text-brand-ink hover:border-brand-line-active hover:bg-neutral-50"
        >
          다시 시도
        </button>
      </div>
    )
  }

  if (branches === undefined || branches.length === 0) {
    return <p className="text-[12px] text-brand-faint">선택할 수 있는 브랜치가 없습니다.</p>
  }

  const selected = branches.find((branch) => branch.name === value)

  return (
    <div>
      <label htmlFor={inputId} className={LABEL}>
        분석할 브랜치
      </label>
      <select
        id={inputId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 w-full rounded-[10px] border border-neutral-300 bg-white px-2.5 py-2 text-[13px] font-medium text-brand-ink focus:border-brand-600 focus:outline-none"
      >
        {branches.map((branch) => (
          <option key={branch.name} value={branch.name}>
            {branch.name}
            {branch.isProtected ? ' (보호됨)' : ''}
          </option>
        ))}
      </select>
      {selected !== undefined && (
        <p className="mt-1.5 font-evidence text-[11px] text-brand-faint">
          현재 tip {selected.commitSha.slice(0, 7)}
        </p>
      )}
    </div>
  )
}
