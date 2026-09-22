import type {
  ClauseDto,
  ConditionDto,
  JobMatchItemDto,
  RecommendationDto,
  SkillGapDto,
  SkillGapRowDto,
  WhatIfDto,
} from '@/features/matching/api/types'
import type {
  JobPostingView,
  JobRequirement,
  NextSkillEvidenceStatus,
  NextSkillView,
  RequirementMark,
  SkillGapGroupView,
  SkillGapRowView,
  SkillGapSummaryView,
  SkillGapVerdict,
  WhatIfJobView,
} from '@/features/matching/model/view'
import { EVIDENCE_LEVELS } from '@/shared/types/domain'
import type { EvidenceLevel } from '@/shared/types/domain'
import { targetRoleDisplayName } from '@/features/matching/model/targetOptions'
import { activeMatchingJobCount } from '@/features/matching/model/presentation'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import {
  formatJobDeadline,
  presentUnresolvedRequirement,
} from '@/features/matching/model/presentation'

/**
 * 서버 DTO를 화면 타입으로 옮긴다 (S15P21E102-279).
 *
 * 이 파일이 하는 일은 <b>이름 바꾸기와 묶기</b>뿐이다. 수치를 만들거나 다시 세지
 * 않는다 — 충족 건수, 증가 건수, 비율은 전부 C가 계산한 값이고 화면이 그것을 다시
 * 계산하면 두 숫자가 어긋났을 때 어느 쪽이 맞는지 알 수 없게 된다.
 *
 * 변환을 한곳에 모으는 이유는 판정 어휘가 여러 화면에 흩어지는 것을 막기 위해서다.
 * `UNKNOWN`을 `NONE`으로 접는 실수는 한 화면에서만 나도 규칙 위반이 된다.
 */

const MARKS: readonly RequirementMark[] = ['HAVE', 'WEAK', 'NONE', 'UNKNOWN']

/** 모르는 값을 `NONE`으로 떨어뜨리지 않는다. 미보유로 단정하는 것이 가장 나쁜 기본값이다. */
function toMark(value: string | null | undefined): RequirementMark {
  return MARKS.includes(value as RequirementMark) ? (value as RequirementMark) : 'UNKNOWN'
}

function toLevel(value: string | null | undefined): EvidenceLevel | null {
  return EVIDENCE_LEVELS.includes(value as EvidenceLevel) ? (value as EvidenceLevel) : null
}

/**
 * 절 하나를 칩 하나로.
 *
 * 절은 기술 여러 개의 OR일 수 있어(`Kafka 또는 RabbitMQ`) 이름을 `/`로 잇는다.
 * 첫 기술만 보여 주면 화면이 요구를 좁혀 말하게 된다.
 */
function toRequirement(clause: ClauseDto): JobRequirement {
  return {
    techName:
      clause.techIds.length === 0
        ? '확인되지 않은 기술'
        : clause.techIds.map((techId) => technologyDisplayName(techId)).join(' / '),
    mark: toMark(clause.mark),
    requiredLevel: toLevel(clause.requiredLevel),
  }
}

function toRequirements(condition: ConditionDto | null): JobRequirement[] {
  return condition === null ? [] : condition.clauses.map(toRequirement)
}

export function toJobPosting(item: JobMatchItemDto): JobPostingView {
  return {
    id: item.jobId,
    title: item.title ?? '제목 없음',
    companyName: item.companyName ?? '',
    region: item.region,
    career: item.careerLevel,
    deadlineText: formatJobDeadline(item.deadline),
    sourceSite: item.sourceSite,
    sourceUrl: item.sourceUrl,
    requiredStatus: item.requiredStatus ?? 'UNKNOWN',
    fulfillmentRatio: item.fulfillmentRatio,
    required: toRequirements(item.required),
    preferred: toRequirements(item.preferred),
    unresolved: [
      ...(item.required?.unresolved ?? []),
      ...(item.preferred?.unresolved ?? []),
    ].map((unresolved) => presentUnresolvedRequirement(unresolved, technologyDisplayName)),
  }
}

const VERDICTS: readonly SkillGapVerdict[] = [
  'MET',
  'LEVEL_SHORT',
  'NO_EVIDENCE',
  'UNDETERMINED',
]

/** 모르는 판정은 미판정으로 둔다. 부족으로 떨어뜨리면 없는 결핍이 생긴다. */
function toVerdict(value: string): SkillGapVerdict {
  return VERDICTS.includes(value as SkillGapVerdict)
    ? (value as SkillGapVerdict)
    : 'UNDETERMINED'
}

const VERDICT_TEXT: Readonly<Record<SkillGapVerdict, string>> = {
  MET: '충족',
  LEVEL_SHORT: '수준 부족',
  NO_EVIDENCE: '미보유',
  UNDETERMINED: '미판정',
}

const GROUP_TITLE: Readonly<Record<SkillGapVerdict, { title: string; description: string }>> = {
  MET: { title: '충족', description: '공고가 요구하는 수준을 충족합니다' },
  LEVEL_SHORT: {
    title: '보완이 필요한 기술',
    description: '현재 확인된 수준보다 더 높은 수준을 요구합니다',
  },
  NO_EVIDENCE: {
    title: '새로 준비할 기술',
    description: '공고에서 요구하지만 현재 분석에서 사용 근거를 찾지 못했습니다',
  },
  UNDETERMINED: {
    title: '판단 근거 부족',
    description: '평가하지 않은 기술입니다. 부족으로 세지 않습니다',
  },
}

function toSkillGapRow(row: SkillGapRowDto): SkillGapRowView {
  const verdict = toVerdict(row.verdict)
  return {
    techName: technologyDisplayName(row.techId),
    requiredCount: row.requiredCount,
    preferredCount: row.preferredCount,
    personalLevel: toLevel(row.personalLevel),
    verdict,
    verdictText: VERDICT_TEXT[verdict],
    fillDelta: row.fillDelta,
  }
}

/**
 * 판정별 묶음. 빈 묶음은 만들지 않는다.
 *
 * 순서를 고정하는 이유는 사용자가 매번 같은 자리에서 같은 묶음을 찾게 하려는 것이다.
 * 행 수로 정렬하면 분석할 때마다 표의 구조가 바뀐다.
 */
export function toSkillGapGroups(rows: readonly SkillGapRowDto[]): SkillGapGroupView[] {
  const views = rows.map(toSkillGapRow)
  return VERDICTS.map((verdict) => ({
    verdict,
    title: GROUP_TITLE[verdict].title,
    description: GROUP_TITLE[verdict].description,
    rows: views.filter((row) => row.verdict === verdict),
  })).filter((group) => group.rows.length > 0)
}

/**
 * 요약.
 *
 * 합계를 화면에서 다시 더하지 않는다. 서버가 준 값과 어긋나면 그 사실이 보여야 하고,
 * 화면이 합을 만들면 그 불일치가 감춰진다.
 */
export function toSkillGapSummary(dto: SkillGapDto): SkillGapSummaryView | null {
  if (dto.summary === null) {
    return null
  }
  const jobCount = activeMatchingJobCount(dto.basis)
  const role = targetRoleDisplayName(dto.basis.targetRole)
  return {
    basisText: jobCount === null ? role : `${role} · 수요 산정 공고 ${jobCount}건`,
    requiredTechCount: dto.summary.requiredTechCount,
    metCount: dto.summary.metCount,
    gapCount: dto.summary.gapCount,
    gapBreakdown: `미보유 ${dto.summary.noEvidenceCount} · 수준 부족 ${dto.summary.levelShortCount}`,
    undeterminedCount: dto.summary.undeterminedCount,
  }
}

const EVIDENCE_STATUSES: readonly NextSkillEvidenceStatus[] = [
  'NOT_HELD',
  'L0',
  'PERSONAL_LEVEL_UNKNOWN',
]

/**
 * 모르는 값을 `NOT_HELD`로 떨어뜨리지 않는다.
 *
 * 기본값을 미보유로 두면 계약이 늘어났을 때 화면이 조용히 "보유하지 않았다"고 말하게
 * 된다. `toMark`가 `UNKNOWN`으로 남기는 것과 같은 이유이고, 여기서는 주장할 상태가
 * 없다는 뜻으로 `null`이 그 자리다.
 */
function toEvidenceStatus(value: string | null | undefined): NextSkillEvidenceStatus | null {
  return EVIDENCE_STATUSES.includes(value as NextSkillEvidenceStatus)
    ? (value as NextSkillEvidenceStatus)
    : null
}

export function toNextSkills(dto: RecommendationDto): NextSkillView[] {
  return dto.candidates.map((candidate) => ({
    techId: candidate.techId,
    rank: candidate.rank,
    techName: technologyDisplayName(candidate.techId),
    fromLevel: toLevel(candidate.personalLevel),
    evidenceStatus: toEvidenceStatus(candidate.evidenceStatus),
    requiredImpactCount: candidate.impact?.requiredCount ?? null,
    preferredImpactCount: candidate.impact?.preferredCount ?? null,
    affectedJobCount: candidate.impact?.affectedCount ?? null,
    requiredCount: candidate.demand?.requiredCount ?? null,
    reasons: candidate.reasons,
    unknownPrerequisiteTechIds: candidate.unknownPrerequisiteTechIds,
    missingPrerequisiteTechIds: candidate.missingPrerequisiteTechIds,
  }))
}

/** 값이 없는 축은 빼고 잇는다. `서울 · ` 같은 꼬리를 남기지 않기 위해서다. */
export function toWhatIfJobs(dto: WhatIfDto): WhatIfJobView[] {
  return dto.items.map((item) => ({
    id: item.jobId,
    title: item.title ?? '제목 없음',
    meta: [item.companyName, item.region, item.careerLevel].filter(Boolean).join(' · '),
    sourceUrl: item.sourceUrl,
    requiredImpact: item.requiredImpact,
    preferredImpact: item.preferredImpact,
    conditional: item.eligibility === 'CONDITIONAL',
  }))
}
