import type {
  AnalysisAccepted,
  AnalysisRequestOutcome,
  RepositorySummary,
} from '@/features/analysis/api/types'

/** 저장소 선택 화면의 현재 browser history entry에 보관하는 복원용 스냅샷. */
export const ANALYSIS_SELECTION_HISTORY_KEY = 'analysisSelectionDraft'

export interface AnalysisSelectionDraft {
  version: 1
  repositories: RepositorySummary[]
  branches: Array<[fullName: string, branchName: string]>
  accepted: AnalysisAccepted[]
}

/**
 * 진행 화면에서 뒤로 왔을 때 필요한 값만 직렬화한다.
 * Error 인스턴스를 포함하는 실패 결과는 보관하지 않아 실패 건을 다시 시도할 수 있게 한다.
 */
export function createAnalysisSelectionDraft(
  repositories: Iterable<RepositorySummary>,
  branches: ReadonlyMap<string, string>,
  outcomes: ReadonlyMap<string, AnalysisRequestOutcome>,
): AnalysisSelectionDraft {
  return {
    version: 1,
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
  if (!isRecord(candidate) || candidate.version !== 1) {
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
    version: 1,
    repositories: candidate.repositories,
    branches: candidate.branches,
    accepted: candidate.accepted,
  }
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
    typeof value.pollAfterSec === 'number' &&
    isString(value.statusUrl)
  )
}
