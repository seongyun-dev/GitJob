/**
 * 좌표에서 기술 식별자를 만든다.
 *
 * BE `TechnologyCandidateAdminService.normalizeTechId`와 같은 규칙이다.
 * 여기서 다시 구현하는 이유는 하나뿐이다 — 승격 폼에 미리 채워 넣어 관리자가
 * 무엇이 등록될지 보고 고칠 수 있게 하려는 것이다. 판정은 서버가 한다.
 */
export function deriveTechId(coordinate: string): string {
  return coordinate
    .toLowerCase()
    .replace(/^@/, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** BE 정규식 `^[a-z0-9][a-z0-9-]{0,79}$`와 같다. */
export function isValidTechId(techId: string): boolean {
  return /^[a-z0-9][a-z0-9-]{0,79}$/.test(techId)
}

/** technology_category.job_domain 에 실제로 쓰이는 값 (V7 시드 기준). */
export const JOB_DOMAINS = ['BACKEND', 'FRONTEND', 'AI_DATA', 'INFRASTRUCTURE'] as const

export type JobDomain = (typeof JOB_DOMAINS)[number]

const JOB_DOMAIN_LABELS: Readonly<Record<JobDomain, string>> = {
  BACKEND: '백엔드',
  FRONTEND: '프론트엔드',
  AI_DATA: 'AI · 데이터',
  INFRASTRUCTURE: '인프라',
}

export function jobDomainLabel(domain: JobDomain): string {
  return JOB_DOMAIN_LABELS[domain]
}
