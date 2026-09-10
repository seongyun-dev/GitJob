import { isApiFailure, isApiSuccess } from '@/shared/api/envelope'
import {
  CLIENT_ENVELOPE,
  CLIENT_NETWORK,
  httpFallbackCode,
  resolveErrorAction,
} from '@/shared/api/errorCodes'
import type { ErrorAction } from '@/shared/api/errorCodes'
import type { ApiSuccess } from '@/shared/types/api'

/**
 * Base URL (계약 1-5).
 *
 * 인프라가 주는 `VITE_API_BASE_URL`은 nginx의 REST 루트(`/api`)이지 버전 경로가 아니다
 * (`Infra/docker/frontend/Dockerfile`의 `ARG VITE_API_BASE_URL=/api`, 루트 `.env.example`).
 * 버전은 라우팅이 아니라 FE·BE 계약이므로 여기서 붙인다. 이 값을 그대로 쓰면
 * 운영 빌드가 `/api/me/...`로 나가 BE의 `/api/v1/me/...`에 닿지 못한다.
 *
 * 개발 서버는 vite proxy가 백엔드(:8080)로 넘긴다.
 * 같은 오리진으로 요청하므로 CORS 없이 세션 쿠키가 오간다.
 */
const API_ROOT = import.meta.env.VITE_API_BASE_URL ?? '/api'

/**
 * OAuth 시작처럼 `fetch`가 아니라 브라우저 이동으로 호출하는 엔드포인트도 있어
 * 내보낸다. 베이스 계산이 두 곳에 생기면 위 주석의 함정을 한쪽만 피하게 된다.
 */
export const API_BASE_URL = `${API_ROOT.replace(/\/$/, '')}/v1`

/**
 * 서버가 봉투로 내려준 실패를 그대로 담는 오류.
 *
 * `action`을 여기서 미리 계산해 두면 화면은 코드 문자열을 몰라도 된다.
 * `status`는 QueryClient의 4xx 재시도 판정에 쓰인다(app/providers.tsx).
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly action: ErrorAction
  readonly retryAfterSec: number | null

  constructor(params: {
    status: number
    code: string
    message: string
    retryAfterSec?: number | null
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.status = params.status
    this.code = params.code
    this.action = resolveErrorAction(params.code)
    this.retryAfterSec = params.retryAfterSec ?? null
  }
}

function parseRetryAfter(response: Response): number | null {
  const header = response.headers.get('Retry-After')
  if (header === null) {
    return null
  }
  const seconds = Number.parseInt(header, 10)
  return Number.isNaN(seconds) ? null : seconds
}

/**
 * 인증은 HttpOnly 세션 쿠키로 하므로 모든 요청에 credentials를 포함한다(설계 §6-2).
 * 응답은 항상 공통 봉투이므로 봉투 형태가 아니면 오류로 처리한다.
 */
export async function request<T>(path: string, init?: RequestInit): Promise<ApiSuccess<T>> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(init?.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...init?.headers,
      },
    })
  } catch {
    // 네트워크 단절·CORS 차단 등 응답 자체가 없는 경우. 원인 문자열은 노출하지 않는다.
    throw new ApiError({
      status: 0,
      code: CLIENT_NETWORK,
      message: '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    })
  }

  // 모든 응답은 봉투를 쓴다(계약 1-1). 본문이 없거나 JSON이 아니면 아래에서 형식 오류로 처리된다.
  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    if (isApiFailure(body)) {
      throw new ApiError({
        status: response.status,
        code: body.code,
        message: body.message,
        retryAfterSec: parseRetryAfter(response),
      })
    }
    // 봉투가 아닌 오류 응답(프록시 오류, Spring 기본 404 등)
    throw new ApiError({
      status: response.status,
      code: httpFallbackCode(response.status),
      message: '요청을 처리할 수 없습니다.',
      retryAfterSec: parseRetryAfter(response),
    })
  }

  if (!isApiSuccess<T>(body)) {
    throw new ApiError({
      status: response.status,
      code: CLIENT_ENVELOPE,
      message: '서버 응답 형식이 올바르지 않습니다.',
    })
  }

  return body
}

/** 조회용. 봉투를 벗겨 data만 돌려준다. */
export async function get<T>(path: string): Promise<T> {
  const envelope = await request<T>(path)
  return envelope.data
}

/** 전량 교체 쓰기용(명세는 PUT 전량 교체를 기본으로 한다). */
export async function put<T>(path: string, body: unknown): Promise<T> {
  const envelope = await request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
  return envelope.data
}

/**
 * 생성·행위 호출용. `POST /analyses`(티켓 117)와 관리자 결정(티켓 14)이 쓴다.
 *
 * `put`과 본문이 같지만 method가 계약의 일부다. 호출부에서 `request`에 직접
 * `{ method: 'POST' }`를 넘기면 봉투 해제 코드가 기능마다 복제된다.
 *
 * `body`가 선택인 이유는 본문 없는 POST가 있기 때문이다(초안 발행). 넘기지
 * 않으면 `request`가 Content-Type을 붙이지 않고 빈 본문으로 나간다.
 */
export async function post<T>(path: string, body?: unknown): Promise<T> {
  const envelope = await request<T>(path, {
    method: 'POST',
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  return envelope.data
}
