import {
  EVIDENCE_FACT_TYPES,
  EVIDENCE_ITEM_SCOPES,
  TECHNOLOGY_CATEGORY_CODES,
  type EvidenceFactType,
  type EvidenceItem,
  type EvidenceItemScope,
  type ExcludedCounts,
  type NextAction,
  type ProfileCriteria,
  type TechnologyCategory,
  type TechnologyCategoryCode,
  type TechnologyEvidence,
  type TechnologyProfile,
  type TechnologyProfileEntry,
  type UnmetRule,
} from '@/features/evidence/api/types'
import { ApiError } from '@/shared/api/client'
import { CLIENT_ENVELOPE } from '@/shared/api/errorCodes'
import { EVIDENCE_LEVELS, type EvidenceLevel } from '@/shared/types/domain'

/**
 * Evidence 응답의 런타임 파싱 · 티켓 S15P21E102-208.
 *
 * **왜 타입 선언만으로 끝내지 않는가.** `types.ts`의 interface는 컴파일 시점 약속일
 * 뿐이고 응답은 런타임 값이다. 이 계약은 BE 구현 **전에** 명세만 보고 쓴 것이라 실제
 * 응답으로 검증한 적이 없다. 선언만 두면 BE가 다른 모양을 내려보낼 때 `undefined`가
 * 화면 깊은 곳까지 흘러가 "Level 미정"처럼 보이는 오작동이 된다. 계약이 어긋났다는
 * 사실이 그 자리에서 드러나야 한다.
 *
 * `client.ts`는 봉투(`{ message, data }`)까지만 검사하고 `data` 안쪽은 보지 않는다.
 * 안쪽을 보는 책임이 이 파일이다.
 *
 * **어긋나면 항목을 버리지 않고 응답 전체를 실패시킨다.** 근거 한 줄을 조용히
 * 떨어뜨리면 사용자는 실제보다 근거가 적다고 믿게 되는데, 이 제품에서 그건 표시
 * 오류가 아니라 사실 왜곡이다. 근거 목록이 불완전한 채 보이는 것보다 오류 화면이 낫다.
 *
 * 실패는 `CLIENT-ENVELOPE`로 낸다. 계약 1-3이 이미 그 코드를 "2xx인데 본문이 성공
 * 봉투가 아님 → `SHOW_GENERIC_ERROR`"로 매핑해 두었고, 안쪽 모양이 어긋난 것도
 * 사용자가 할 수 있는 일이 없다는 점에서 같은 처리다. 새 코드를 만들지 않는다.
 */

/** 파싱 실패. 4xx가 아니므로 `providers.tsx`의 재시도 판정에서 5xx와 같이 취급된다. */
function envelopeError(detail: string): ApiError {
  if (import.meta.env.DEV) {
    console.error(`[evidence] 응답 형태가 명세와 다릅니다: ${detail}`)
  }
  return new ApiError({
    status: 200,
    code: CLIENT_ENVELOPE,
    message: '서버 응답 형식이 올바르지 않습니다.',
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readRecord(
  source: Record<string, unknown>,
  field: string,
  at: string,
): Record<string, unknown> {
  const value = source[field]
  if (!isRecord(value)) {
    throw envelopeError(`${at}.${field}가 객체가 아닙니다`)
  }
  return value
}

function readArray(source: Record<string, unknown>, field: string, at: string): unknown[] {
  const value = source[field]
  if (!Array.isArray(value)) {
    throw envelopeError(`${at}.${field}가 배열이 아닙니다`)
  }
  return value
}

function readString(source: Record<string, unknown>, field: string, at: string): string {
  const value = source[field]
  if (typeof value !== 'string' || value === '') {
    throw envelopeError(`${at}.${field}가 비어 있지 않은 문자열이 아닙니다`)
  }
  return value
}

function readBoolean(source: Record<string, unknown>, field: string, at: string): boolean {
  const value = source[field]
  if (typeof value !== 'boolean') {
    throw envelopeError(`${at}.${field}가 boolean이 아닙니다`)
  }
  return value
}

/** 건수·상한 등. 0은 의미 있는 값이므로 허용하고 음수와 소수는 막는다. */
function readCount(source: Record<string, unknown>, field: string, at: string): number {
  const value = source[field]
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw envelopeError(`${at}.${field}가 0 이상의 정수가 아닙니다`)
  }
  return value
}

/** `null`은 "값이 없다"로 통과시키고, 빈 문자열은 통과시키지 않는다. */
function readNullableString(
  source: Record<string, unknown>,
  field: string,
  at: string,
): string | null {
  const value = source[field]
  if (value === null) {
    return null
  }
  if (typeof value !== 'string' || value === '') {
    throw envelopeError(`${at}.${field}가 문자열도 null도 아닙니다`)
  }
  return value
}

/**
 * 줄 번호. 1 이상의 정수만 받는다. `DEPENDENCY`는 매니페스트에서 나와 줄이 없을 수
 * 있으므로 `null`은 정상이고, 0은 "없음"의 대체 표기로 받아들이지 않는다.
 */
function readLineNo(source: Record<string, unknown>, at: string): number | null {
  const value = source['lineNo']
  if (value === null) {
    return null
  }
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
    throw envelopeError(`${at}.lineNo가 1 이상의 정수도 null도 아닙니다`)
  }
  return value
}

function readStringArray(source: Record<string, unknown>, field: string, at: string): string[] {
  return readArray(source, field, at).map((entry, index) => {
    if (typeof entry !== 'string' || entry === '') {
      throw envelopeError(`${at}.${field}[${index}]가 비어 있지 않은 문자열이 아닙니다`)
    }
    return entry
  })
}

/**
 * 고정 어휘 판정.
 *
 * 여기서는 `lookupLabel`처럼 모르는 값을 넘기고 DEV 경고만 내지 않는다. 그쪽은
 * 배지 하나를 렌더하지 않는 선택이지만, 이 값들은 Level·범위·fact 종류·카테고리처럼
 * **의미를 결정하는 축**이라 모르는 값이 들어오면 그 근거를 해석할 방법이 없다.
 */
function readEnum<T extends string>(
  source: Record<string, unknown>,
  field: string,
  allowed: readonly T[],
  at: string,
): T {
  const value = source[field]
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    throw envelopeError(
      `${at}.${field}가 ${allowed.join(' · ')} 중 하나가 아닙니다: ${String(value)}`,
    )
  }
  return value as T
}

function readLevel(source: Record<string, unknown>, field: string, at: string): EvidenceLevel {
  return readEnum<EvidenceLevel>(source, field, EVIDENCE_LEVELS, at)
}

function parseCommitSha(raw: unknown, at: string): { repoFullName: string; commitSha: string } {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  return {
    repoFullName: readString(raw, 'repoFullName', at),
    commitSha: readString(raw, 'commitSha', at),
  }
}

/**
 * 판정 기준. 명세가 "숫자를 반환하므로 criteria 객체를 반드시 함께 반환한다"고
 * 못 박았으므로 optional로 두지 않는다. 없으면 수치의 출처가 사라진다.
 */
function parseProfileCriteria(raw: unknown, at: string): ProfileCriteria {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  const limits = readRecord(raw, 'limits', at)
  return {
    registryVersion: readString(raw, 'registryVersion', at),
    registryChecksum: readString(raw, 'registryChecksum', at),
    repositoryCount: readCount(raw, 'repositoryCount', at),
    analyzedRepositoryCount: readCount(raw, 'analyzedRepositoryCount', at),
    commitShas: readArray(raw, 'commitShas', at).map((entry, index) =>
      parseCommitSha(entry, `${at}.commitShas[${index}]`),
    ),
    limits: {
      maxRepositories: readCount(limits, 'maxRepositories', `${at}.limits`),
      maxFilesPerRepository: readCount(limits, 'maxFilesPerRepository', `${at}.limits`),
    },
  }
}

function parseProfileEntry(raw: unknown, at: string): TechnologyProfileEntry {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  return {
    techId: readString(raw, 'techId', at),
    techName: readString(raw, 'techName', at),
    repoLevel: readLevel(raw, 'repoLevel', at),
    personalLevel: readLevel(raw, 'personalLevel', at),
    evidenceCount: readCount(raw, 'evidenceCount', at),
    representativeRepo: readString(raw, 'representativeRepo', at),
    lastUsedAt: readString(raw, 'lastUsedAt', at),
  }
}

function parseCategory(raw: unknown, at: string): TechnologyCategory {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  return {
    categoryCode: readEnum<TechnologyCategoryCode>(
      raw,
      'categoryCode',
      TECHNOLOGY_CATEGORY_CODES,
      at,
    ),
    categoryName: readString(raw, 'categoryName', at),
    technologies: readArray(raw, 'technologies', at).map((entry, index) =>
      parseProfileEntry(entry, `${at}.technologies[${index}]`),
    ),
  }
}

/**
 * 알려진 필드만 새 객체로 옮겨 담는다.
 *
 * 통과시키는 게 아니라 **옮겨 담는** 것이 요점이다. 명세가 금지한 원본 코드 본문이나
 * FE 확정 규칙과 충돌하는 `contributionScore`가 응답에 실려 와도 FE 상태·캐시·
 * devtools에 들어오지 않는다(`types.ts`의 `EvidenceItem` 주석 참조).
 */
function parseEvidenceItem(raw: unknown, at: string): EvidenceItem {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  return {
    evidenceId: readCount(raw, 'evidenceId', at),
    scopeType: readEnum<EvidenceItemScope>(raw, 'scopeType', EVIDENCE_ITEM_SCOPES, at),
    level: readLevel(raw, 'level', at),
    matchedRule: readString(raw, 'matchedRule', at),
    factType: readEnum<EvidenceFactType>(raw, 'factType', EVIDENCE_FACT_TYPES, at),
    repoFullName: readString(raw, 'repoFullName', at),
    filePath: readString(raw, 'filePath', at),
    lineNo: readLineNo(raw, at),
    commitSha: readString(raw, 'commitSha', at),
    permalink: readString(raw, 'permalink', at),
    inherited: readBoolean(raw, 'inherited', at),
    detectedAt: readString(raw, 'detectedAt', at),
    excludedReason: readNullableString(raw, 'excludedReason', at),
  }
}

function parseUnmetRule(raw: unknown, at: string): UnmetRule {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  return { rule: readString(raw, 'rule', at), description: readString(raw, 'description', at) }
}

function parseNextAction(raw: unknown, at: string): NextAction {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  return {
    fromLevel: readLevel(raw, 'fromLevel', at),
    targetLevel: readLevel(raw, 'targetLevel', at),
    ruleId: readString(raw, 'ruleId', at),
    message: readString(raw, 'message', at),
  }
}

/** 제외 건수. 0이 의미 있는 값이라 다섯 종류를 모두 요구한다. */
function parseExcludedCounts(raw: unknown, at: string): ExcludedCounts {
  if (!isRecord(raw)) {
    throw envelopeError(`${at}가 객체가 아닙니다`)
  }
  return {
    bot: readCount(raw, 'bot', at),
    merge: readCount(raw, 'merge', at),
    forkBase: readCount(raw, 'forkBase', at),
    formatOnly: readCount(raw, 'formatOnly', at),
    generated: readCount(raw, 'generated', at),
  }
}

/** `GET /me/profile` 응답 · 명세 B-FN-010. */
export function parseTechnologyProfile(raw: unknown): TechnologyProfile {
  const at = 'profile'
  if (!isRecord(raw)) {
    throw envelopeError(`${at} 응답이 객체가 아닙니다`)
  }
  return {
    analysisId: readString(raw, 'analysisId', at),
    analyzedAt: readString(raw, 'analyzedAt', at),
    partial: readBoolean(raw, 'partial', at),
    missingScope: readStringArray(raw, 'missingScope', at),
    criteria: parseProfileCriteria(raw['criteria'], `${at}.criteria`),
    categories: readArray(raw, 'categories', at).map((entry, index) =>
      parseCategory(entry, `${at}.categories[${index}]`),
    ),
    judgementLimits: readStringArray(raw, 'judgementLimits', at),
  }
}

/** `GET /me/technologies/{techId}/evidence` 응답 · 명세 B-FN-011. */
export function parseTechnologyEvidence(raw: unknown): TechnologyEvidence {
  const at = 'evidence'
  if (!isRecord(raw)) {
    throw envelopeError(`${at} 응답이 객체가 아닙니다`)
  }
  const criteria = readRecord(raw, 'criteria', at)
  return {
    techId: readString(raw, 'techId', at),
    techName: readString(raw, 'techName', at),
    repoLevel: readLevel(raw, 'repoLevel', at),
    personalLevel: readLevel(raw, 'personalLevel', at),
    criteria: {
      analysisId: readString(criteria, 'analysisId', `${at}.criteria`),
      registryVersion: readString(criteria, 'registryVersion', `${at}.criteria`),
    },
    evidences: readArray(raw, 'evidences', at).map((entry, index) =>
      parseEvidenceItem(entry, `${at}.evidences[${index}]`),
    ),
    unmetRules: readArray(raw, 'unmetRules', at).map((entry, index) =>
      parseUnmetRule(entry, `${at}.unmetRules[${index}]`),
    ),
    nextActions: readArray(raw, 'nextActions', at).map((entry, index) =>
      parseNextAction(entry, `${at}.nextActions[${index}]`),
    ),
    excludedCounts: parseExcludedCounts(raw['excludedCounts'], `${at}.excludedCounts`),
  }
}
