import {
  REQUIREMENT_MARKS,
  SKILL_GAP_VERDICTS,
  type GapHighlight,
  type JobDemand,
  type JobDemandList,
  type JobMatchKpi,
  type JobPosting,
  type JobPostingList,
  type JobRequirement,
  type JobRole,
  type JobRoleList,
  type LearningTarget,
  type NextSkill,
  type Recommendations,
  type RoleTopSkill,
  type SkillGap,
  type SkillGapGroup,
  type SkillGapRow,
  type SkillGapSummary,
  type TargetRole,
  type WhatIfJob,
} from '@/features/matching/api/types'
import { readers } from '@/shared/api/parse'
import { DATA_STATUSES, EVIDENCE_LEVELS } from '@/shared/types/domain'

/**
 * 매칭 계열 응답의 런타임 파싱 · 티켓 S15P21E102-281.
 *
 * 계약이 BE 구현 전에 명세만 보고 쓴 것이라 실제 응답으로 검증한 적이 없다. 왜 선언만
 * 두지 않는지는 `shared/api/parse.ts` 머리말에 적었다.
 *
 * **어긋나면 항목을 버리지 않고 응답 전체를 실패시킨다.** 공고 한 건이나 Gap 한 줄을
 * 조용히 떨어뜨리면 사용자는 실제보다 공고가 적다고, 부족한 기술이 적다고 믿게 되는데,
 * 이 제품에서 그건 표시 오류가 아니라 사실 왜곡이다. 목록이 불완전한 채 보이는 것보다
 * 오류 화면이 낫다.
 */

const r = readers('matching')

function parseRequirement(value: unknown, at: string): JobRequirement {
  const source = r.item(value, at)
  return {
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    mark: r.enum(source, 'mark', at, REQUIREMENT_MARKS),
  }
}

function parseRequirements(source: Record<string, unknown>, field: string, at: string) {
  return r
    .array(source, field, at)
    .map((item, index) => parseRequirement(item, `${at}.${field}[${index}]`))
}

/* ------------------------------------------------------------------ *
 * 목표 직무
 * ------------------------------------------------------------------ */

function parseRoleTopSkill(value: unknown, at: string): RoleTopSkill {
  const source = r.item(value, at)
  return {
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    requiredCount: r.number(source, 'requiredCount', at),
    mark: r.enum(source, 'mark', at, REQUIREMENT_MARKS),
    levelText: r.string(source, 'levelText', at),
  }
}

function parseJobRole(value: unknown, at: string): JobRole {
  const source = r.item(value, at)
  return {
    id: r.string(source, 'id', at),
    name: r.string(source, 'name', at),
    summary: r.string(source, 'summary', at),
    jobCount: r.number(source, 'jobCount', at),
    fullMatchCount: r.number(source, 'fullMatchCount', at),
    note: r.string(source, 'note', at),
    topSkills: r
      .array(source, 'topSkills', at)
      .map((item, index) => parseRoleTopSkill(item, `${at}.topSkills[${index}]`)),
  }
}

export function parseJobRoleList(value: unknown): JobRoleList {
  const at = 'jobRoleList'
  const source = r.root(value, at)
  return {
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    roles: r.array(source, 'roles', at).map((item, i) => parseJobRole(item, `${at}.roles[${i}]`)),
  }
}

export function parseTargetRole(value: unknown): TargetRole {
  const at = 'targetRole'
  const source = r.root(value, at)
  return {
    roleId: r.nullableString(source, 'roleId', at),
    roleName: r.nullableString(source, 'roleName', at),
    updatedAt: r.nullableString(source, 'updatedAt', at),
  }
}

/* ------------------------------------------------------------------ *
 * 공고 · 수요
 * ------------------------------------------------------------------ */

function parseKpi(source: Record<string, unknown>, at: string): JobMatchKpi {
  const kpi = r.record(source, 'kpi', at)
  const kpiAt = `${at}.kpi`
  return {
    total: r.number(kpi, 'total', kpiAt),
    fullMatch: r.number(kpi, 'fullMatch', kpiAt),
    nearMatch: r.number(kpi, 'nearMatch', kpiAt),
    lowMatch: r.number(kpi, 'lowMatch', kpiAt),
    scopeText: r.string(kpi, 'scopeText', kpiAt),
  }
}

function parseGapHighlight(value: unknown, at: string): GapHighlight {
  const source = r.item(value, at)
  return {
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    requiredCount: r.number(source, 'requiredCount', at),
    levelText: r.string(source, 'levelText', at),
  }
}

function parseJobPosting(value: unknown, at: string): JobPosting {
  const source = r.item(value, at)
  return {
    id: r.string(source, 'id', at),
    title: r.string(source, 'title', at),
    region: r.string(source, 'region', at),
    career: r.string(source, 'career', at),
    deadline: r.string(source, 'deadline', at),
    required: parseRequirements(source, 'required', at),
    preferred: parseRequirements(source, 'preferred', at),
  }
}

export function parseJobPostingList(value: unknown): JobPostingList {
  const at = 'jobPostingList'
  const source = r.root(value, at)
  return {
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    headline: r.string(source, 'headline', at),
    kpi: parseKpi(source, at),
    gapTitle: r.string(source, 'gapTitle', at),
    gaps: r.array(source, 'gaps', at).map((item, i) => parseGapHighlight(item, `${at}.gaps[${i}]`)),
    items: r.array(source, 'items', at).map((item, i) => parseJobPosting(item, `${at}.items[${i}]`)),
    page: r.number(source, 'page', at),
    size: r.number(source, 'size', at),
    totalCount: r.number(source, 'totalCount', at),
  }
}

function parseJobDemand(value: unknown, at: string): JobDemand {
  const source = r.item(value, at)
  return {
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    requiredCount: r.number(source, 'requiredCount', at),
    preferredCount: r.number(source, 'preferredCount', at),
  }
}

export function parseJobDemandList(value: unknown): JobDemandList {
  const at = 'jobDemandList'
  const source = r.root(value, at)
  return {
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    basisText: r.string(source, 'basisText', at),
    items: r.array(source, 'items', at).map((item, i) => parseJobDemand(item, `${at}.items[${i}]`)),
  }
}

/* ------------------------------------------------------------------ *
 * Skill Gap
 * ------------------------------------------------------------------ */

function parseSkillGapRow(value: unknown, at: string): SkillGapRow {
  const source = r.item(value, at)
  return {
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    requiredCount: r.number(source, 'requiredCount', at),
    preferredCount: r.nullableNumber(source, 'preferredCount', at),
    personalLevel: r.nullableEnum(source, 'personalLevel', at, EVIDENCE_LEVELS),
    verdict: r.enum(source, 'verdict', at, SKILL_GAP_VERDICTS),
    verdictText: r.string(source, 'verdictText', at),
    fillDelta: r.nullableNumber(source, 'fillDelta', at),
  }
}

function parseSkillGapGroup(value: unknown, at: string): SkillGapGroup {
  const source = r.item(value, at)
  return {
    verdict: r.enum(source, 'verdict', at, SKILL_GAP_VERDICTS),
    title: r.string(source, 'title', at),
    description: r.string(source, 'description', at),
    rows: r.array(source, 'rows', at).map((item, i) => parseSkillGapRow(item, `${at}.rows[${i}]`)),
  }
}

function parseSkillGapSummary(source: Record<string, unknown>, at: string): SkillGapSummary {
  const summary = r.record(source, 'summary', at)
  const summaryAt = `${at}.summary`
  return {
    basisText: r.string(summary, 'basisText', summaryAt),
    requiredTechCount: r.number(summary, 'requiredTechCount', summaryAt),
    metCount: r.number(summary, 'metCount', summaryAt),
    gapCount: r.number(summary, 'gapCount', summaryAt),
    gapBreakdown: r.string(summary, 'gapBreakdown', summaryAt),
    undeterminedCount: r.number(summary, 'undeterminedCount', summaryAt),
  }
}

export function parseSkillGap(value: unknown): SkillGap {
  const at = 'skillGap'
  const source = r.root(value, at)
  return {
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    summary: parseSkillGapSummary(source, at),
    groups: r
      .array(source, 'groups', at)
      .map((item, i) => parseSkillGapGroup(item, `${at}.groups[${i}]`)),
  }
}

/* ------------------------------------------------------------------ *
 * 추천 · What-if · 학습 기술
 * ------------------------------------------------------------------ */

function parseWhatIfJob(value: unknown, at: string): WhatIfJob {
  const source = r.item(value, at)
  return {
    id: r.string(source, 'id', at),
    title: r.string(source, 'title', at),
    meta: r.string(source, 'meta', at),
    chips: parseRequirements(source, 'chips', at),
    why: r.string(source, 'why', at),
  }
}

function parseStringArray(source: Record<string, unknown>, field: string, at: string): string[] {
  return r.array(source, field, at).map((item, index) => {
    if (typeof item !== 'string') {
      throw r.fail(`${at}.${field}[${index}]가 문자열이 아닙니다`)
    }
    return item
  })
}

function parseNextSkill(value: unknown, at: string): NextSkill {
  const source = r.item(value, at)
  return {
    techId: r.string(source, 'techId', at),
    techName: r.string(source, 'techName', at),
    shortName: r.string(source, 'shortName', at),
    fromLevel: r.enum(source, 'fromLevel', at, EVIDENCE_LEVELS),
    targetLevel: r.enum(source, 'targetLevel', at, EVIDENCE_LEVELS),
    currentFullMatch: r.number(source, 'currentFullMatch', at),
    projectedFullMatch: r.number(source, 'projectedFullMatch', at),
    headline: r.string(source, 'headline', at),
    ctaLabel: r.string(source, 'ctaLabel', at),
    reasons: parseStringArray(source, 'reasons', at),
    counterSignals: parseStringArray(source, 'counterSignals', at),
    newlyMatched: r
      .array(source, 'newlyMatched', at)
      .map((item, i) => parseWhatIfJob(item, `${at}.newlyMatched[${i}]`)),
  }
}

export function parseRecommendations(value: unknown): Recommendations {
  const at = 'recommendations'
  const source = r.root(value, at)
  return {
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    recommendationFormulaVersion: r.string(source, 'recommendationFormulaVersion', at),
    whatIfFormulaVersion: r.string(source, 'whatIfFormulaVersion', at),
    skills: r
      .array(source, 'skills', at)
      .map((item, i) => parseNextSkill(item, `${at}.skills[${i}]`)),
  }
}

export function parseLearningTarget(value: unknown): LearningTarget {
  const at = 'learningTarget'
  const source = r.root(value, at)
  return {
    techId: r.nullableString(source, 'techId', at),
    techName: r.nullableString(source, 'techName', at),
    updatedAt: r.nullableString(source, 'updatedAt', at),
  }
}
