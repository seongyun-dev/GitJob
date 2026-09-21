import type {
  AnalysisAccepted,
  AnalysisRequestOutcome,
  RepositorySummary,
} from '@/features/analysis/api/types'

/** 저장소 선택 화면의 현재 browser history entry에 보관하는 복원용 스냅샷. */
export const ANALYSIS_SELECTION_HISTORY_KEY = 'analysisSelectionDraft'

export interface AnalysisSelectionDraft {
  version: 2
  repositories: RepositorySummary[]
  branches: Array<[fullName: string, branchName: string]>
  accepted: AnalysisAccepted[]
  /**
   * 완료 안내를 닫은 묶음. boolean이 아닌 이유는 새 묶음이 시작되면 낡기 때문이다 --
   * ID로 두면 다른 묶음이 오는 순간 안내가 저절로 다시 열린다.
   */
  dismissedBatchId: string | null
}

/**
 * 진행 화면에서 뒤로 왔을 때 필요한 값만 직렬화한다.
 * Error 인스턴스를 포함하는 실패 결과는 보관하지 않아 실패 건을 다시 시도할 수 있게 한다.
 */
export function createAnalysisSelectionDraft(
  repositories: Iterable<RepositorySummary>,
  branches: ReadonlyMap<string, string>,
  outcomes: ReadonlyMap<string, AnalysisRequestOutcome>,
  dismissedBatchId: string | null = null,
): AnalysisSelectionDraft {
  return {
    version: 2,
    dismissedBatchId,
    repositories: [...repositories],
    branches: [...branches.entries()],
    accepted: [...outcomes.values()].flatMap((outcome) =>
      outcome.ok ? [outcome.accepted] : [],
    ),
  }
}

/** history state는 사용자가 조작할 수 있으므로 화면 상태로 쓰기 전에 형태를 검증한다. */
export function readAnalysisSelectionDraft(state: unknown): AnalysisSelectionDraft | null {
  if (!isRecord(state)) {
    return null
  }
  const candidate = state[ANALYSIS_SELECTION_HISTORY_KEY]
  /*
   * v1도 받는다. v2만 받으면 배포 직후 브라우저가 들고 있던 draft가 전부 조용히
   * 버려져, 뒤로 가기로 돌아온 사용자의 선택이 사라진다. 늘어난 필드 하나는
   * 기본값으로 채우면 그만이다.
   */
  if (!isRecord(candidate) || (candidate.version !== 1 && candidate.version !== 2)) {
    return null
  }
  if (
    !Array.isArray(candidate.repositories) ||
    !candidate.repositories.every(isRepositorySummary) ||
    !Array.isArray(candidate.branches) ||
    !candidate.branches.every(isBranchEntry) ||
    !Array.isArray(candidate.accepted) ||
    !candidate.accepted.every(isAnalysisAccepted)
  ) {
    return null
  }
  return {
    version: 2,
    repositories: candidate.repositories,
    branches: candidate.branches,
    accepted: candidate.accepted,
    dismissedBatchId: isString(candidate.dismissedBatchId) ? candidate.dismissedBatchId : null,
  }
}

/** v1 draft에는 없는 값이라 기본은 null이다. */
export function dismissedBatchFromDraft(draft: AnalysisSelectionDraft | null): string | null {
  return draft?.dismissedBatchId ?? null
}

export function selectedFromDraft(
  draft: AnalysisSelectionDraft | null,
): Map<string, RepositorySummary> {
  return new Map((draft?.repositories ?? []).map((repository) => [repository.fullName, repository]))
}

export function branchesFromDraft(draft: AnalysisSelectionDraft | null): Map<string, string> {
  return new Map(draft?.branches ?? [])
}

export function outcomesFromDraft(
  draft: AnalysisSelectionDraft | null,
): Map<string, AnalysisRequestOutcome> {
  return new Map(
    (draft?.accepted ?? []).map((accepted) => [
      accepted.repositoryFullName,
      {
        target: {
          repositoryFullName: accepted.repositoryFullName,
          branchName: accepted.branchName,
        },
        ok: true as const,
        // draft에는 성공한 결과만 담기고, 재사용 여부는 서버 조회가 다시 알려 준다.
        reused: false,
        accepted,
      },
    ]),
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isRepositorySummary(value: unknown): value is RepositorySummary {
  if (!isRecord(value)) {
    return false
  }
  return (
    typeof value.githubRepositoryId === 'number' &&
    isString(value.fullName) &&
    isString(value.name) &&
    isString(value.owner) &&
    typeof value.isPrivate === 'boolean' &&
    isString(value.defaultBranch) &&
    (value.description === null || isString(value.description)) &&
    (value.language === null || isString(value.language)) &&
    isString(value.updatedAt) &&
    typeof value.analyzable === 'boolean'
  )
}

function isBranchEntry(value: unknown): value is [string, string] {
  return Array.isArray(value) && value.length === 2 && value.every(isString)
}

function isAnalysisAccepted(value: unknown): value is AnalysisAccepted {
  if (!isRecord(value)) {
    return false
  }
  return (
    isString(value.analysisId) &&
    isString(value.status) &&
    isString(value.repositoryFullName) &&
    isString(value.branchName) &&
    isString(value.commitSha) &&
    isString(value.statusUrl)
  )
}
