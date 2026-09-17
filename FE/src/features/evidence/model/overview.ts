import type {
  AnalyzedRepository,
  TechnologyVerdict,
} from '@/features/evidence/api/technologiesApi'
import type { EvidenceLevel } from '@/shared/types/domain'

const LEVEL_RANK: Readonly<Record<EvidenceLevel, number>> = {
  L0: 0,
  L1: 1,
  L2: 2,
  L3: 3,
}

export interface ReinforcementItem {
  techId: string
  techName: string
  personalLevel: EvidenceLevel
  repoLevel: EvidenceLevel
  reason: string
}

export interface AnalysisContextRepository {
  repositoryId: string
  name: string
  commitSha: string
  analyzedAt: string
  evidenceCount: number
}

/** 실제 프로필 응답을 우측 패널의 표시 모델로 바꾼다. 판정이나 가짜 값은 만들지 않는다. */
export function buildEvidenceOverviewPanels(
  technologies: readonly TechnologyVerdict[],
  repositories: readonly AnalyzedRepository[],
): {
  reinforcements: ReinforcementItem[]
  repositories: AnalysisContextRepository[]
} {
  return {
    reinforcements: technologies.flatMap((technology) => {
      if (
        technology.personalLevel === null ||
        LEVEL_RANK[technology.personalLevel] >= LEVEL_RANK[technology.repositoryLevel]
      ) {
        return []
      }
      return [
        {
          techId: technology.techId,
          techName: technology.displayName,
          personalLevel: technology.personalLevel,
          repoLevel: technology.repositoryLevel,
          reason: '본인 Commit 근거가 Repository 판정보다 낮습니다.',
        },
      ]
    }),
    repositories: repositories.map((repository) => ({
      repositoryId: repository.repositoryId,
      name: repository.fullName ?? '이름이 기록되지 않은 저장소',
      commitSha: repository.commitSha,
      analyzedAt: repository.analyzedAt,
      evidenceCount: repository.evidenceCount,
    })),
  }
}
