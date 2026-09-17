export const TARGET_ROLES = [
  { value: 'BACKEND', label: '백엔드' },
  { value: 'FRONTEND', label: '프론트엔드' },
  { value: 'AI_DATA', label: 'AI · 데이터' },
  { value: 'INFRASTRUCTURE', label: '인프라' },
  { value: 'MOBILE', label: '모바일' },
] as const

export type TargetRole = (typeof TARGET_ROLES)[number]['value']

const ROLE_ALIASES: Readonly<Record<string, TargetRole>> = {
  BACKEND: 'BACKEND',
  BACKEND_ENGINEER: 'BACKEND',
  FRONTEND: 'FRONTEND',
  FRONTEND_ENGINEER: 'FRONTEND',
  AI_DATA: 'AI_DATA',
  DATA: 'AI_DATA',
  DATA_ENGINEER: 'AI_DATA',
  INFRASTRUCTURE: 'INFRASTRUCTURE',
  DEVOPS: 'INFRASTRUCTURE',
  MOBILE: 'MOBILE',
  MOBILE_ENGINEER: 'MOBILE',
}

export function normalizeTargetRole(value: string | null | undefined): TargetRole | null {
  if (value === null || value === undefined) {
    return null
  }
  return ROLE_ALIASES[value.trim().toUpperCase()] ?? null
}

export function targetRoleDisplayName(value: string | null | undefined): string {
  const role = normalizeTargetRole(value)
  return TARGET_ROLES.find((option) => option.value === role)?.label ?? '선택한 직무'
}

export const TARGET_REGIONS = [
  '서울',
  '경기',
  '인천',
  '부산',
  '대구',
  '대전',
  '광주',
  '울산',
  '세종',
  '강원',
  '충북',
  '충남',
  '전북',
  '전남',
  '경북',
  '경남',
  '제주',
] as const

export type CareerSelection = 'ALL' | 'ENTRY' | 'EXPERIENCED'

export const CAREER_OPTIONS: readonly { value: CareerSelection; label: string }[] = [
  { value: 'ALL', label: '전체' },
  { value: 'ENTRY', label: '신입' },
  { value: 'EXPERIENCED', label: '경력' },
]

export function careerSelectionFromValues(values: readonly string[]): CareerSelection {
  if (values.length === 0) {
    return 'ALL'
  }
  return values.some((value) => value.includes('경력')) ? 'EXPERIENCED' : 'ENTRY'
}

export function careerValues(selection: CareerSelection): string[] {
  if (selection === 'ENTRY') {
    return ['신입']
  }
  if (selection === 'EXPERIENCED') {
    return ['경력']
  }
  return []
}
