import type { ApiFailure, ApiSuccess } from '@/shared/types/api'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** 실패 봉투 `{ code, message }` 판정 */
export function isApiFailure(body: unknown): body is ApiFailure {
  return isRecord(body) && typeof body['code'] === 'string' && typeof body['message'] === 'string'
}

/** 성공 봉투 `{ message, data }` 판정. data는 null도 유효하다(명세 §2-2) */
export function isApiSuccess<T>(body: unknown): body is ApiSuccess<T> {
  return isRecord(body) && typeof body['message'] === 'string' && 'data' in body
}

/** 훅에 넘기기 전 data만 벗긴다(설계 §6-1) */
export function unwrap<T>(envelope: ApiSuccess<T>): T {
  return envelope.data
}
