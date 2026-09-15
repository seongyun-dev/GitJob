import { ApiError } from '@/shared/api/client'
import { CLIENT_ENVELOPE } from '@/shared/api/errorCodes'

/**
 * 응답 `data` 안쪽을 읽는 공용 원시 함수 · 티켓 S15P21E102-281.
 *
 * **왜 타입 선언만으로 끝내지 않는가.** `api/types.ts`의 interface는 컴파일 시점
 * 약속일 뿐이고 응답은 런타임 값이다. 이 저장소가 지금 쓰는 조회 계약 대부분은 BE
 * 구현 **전에** 명세만 보고 쓴 것이라 실제 응답으로 검증한 적이 없다. 선언만 두면
 * BE가 다른 모양을 내려보낼 때 `undefined`가 화면 깊은 곳까지 흘러가 "값이 없음"처럼
 * 보이는 오작동이 된다. 계약이 어긋났다는 사실이 그 자리에서 드러나야 한다.
 *
 * `client.ts`는 봉투(`{ message, data }`)까지만 검사하고 `data` 안쪽은 보지 않는다.
 * 안쪽을 보는 책임이 파서이고, 이 파일은 그 파서들이 쓰는 원시 함수다.
 *
 * 티켓 208이 `features/evidence/api/parseEvidence.ts`에 같은 함수들을 비공개로 두었다.
 * 281이 네 기능(matching·trend·mypage·technology)에 파서를 더 만들면서 다섯 벌이
 * 되므로 여기로 옮긴다. **`parseEvidence.ts`는 이 티켓에서 건드리지 않았다** — 검증된
 * 파일이고 이 티켓의 범위는 새 배선이다. 그쪽을 이 모듈로 바꾸는 것은 별도 정리다.
 *
 * 실패는 전부 `CLIENT-ENVELOPE`로 낸다. 계약 1-3이 이미 그 코드를 "2xx인데 본문이
 * 성공 봉투가 아님 → `SHOW_GENERIC_ERROR`"로 매핑해 두었고, 안쪽 모양이 어긋난 것도
 * 사용자가 할 수 있는 일이 없다는 점에서 같은 처리다. 새 코드를 만들지 않는다.
 */

/**
 * 파싱 실패를 만든다. `scope`는 개발 콘솔에서 어느 기능의 계약이 어긋났는지 가르는
 * 접두이고(`matching` 등), 사용자에게는 노출하지 않는다.
 *
 * `status: 200`인 이유는 HTTP는 성공했기 때문이다. 4xx가 아니므로
 * `providers.tsx`의 재시도 판정에서 5xx와 같이 취급된다.
 */
export function envelopeError(scope: string, detail: string): ApiError {
  if (import.meta.env.DEV) {
    console.error(`[${scope}] 응답 형태가 명세와 다릅니다: ${detail}`)
  }
  return new ApiError({
    status: 200,
    code: CLIENT_ENVELOPE,
    message: '서버 응답 형식이 올바르지 않습니다.',
  })
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * 한 기능의 파서가 쓰는 읽기 함수 묶음.
 *
 * `scope`를 함수마다 넘기지 않으려고 묶어서 만든다. 파서 파일 맨 위에서 한 번
 * `const r = readers('matching')`로 만들고 아래에서 `r.string(...)`처럼 쓴다.
 */
export interface Readers {
  /** 최상위 `data`가 객체인지 본다. 배열 응답은 `rootArray`를 쓴다. */
  root: (value: unknown, at: string) => Record<string, unknown>
  /** 최상위 `data`가 배열인지 본다. */
  rootArray: (value: unknown, at: string) => unknown[]
  record: (source: Record<string, unknown>, field: string, at: string) => Record<string, unknown>
  array: (source: Record<string, unknown>, field: string, at: string) => unknown[]
  string: (source: Record<string, unknown>, field: string, at: string) => string
  number: (source: Record<string, unknown>, field: string, at: string) => number
  boolean: (source: Record<string, unknown>, field: string, at: string) => boolean
  /** `null`을 허용하는 문자열. 필드 자체가 없으면 실패다 — 누락과 명시적 null은 다르다. */
  nullableString: (source: Record<string, unknown>, field: string, at: string) => string | null
  nullableNumber: (source: Record<string, unknown>, field: string, at: string) => number | null
  /** 허용 값 목록에 있는 문자열만 통과시킨다. */
  enum: <T extends string>(
    source: Record<string, unknown>,
    field: string,
    at: string,
    allowed: readonly T[],
  ) => T
  nullableEnum: <T extends string>(
    source: Record<string, unknown>,
    field: string,
    at: string,
    allowed: readonly T[],
  ) => T | null
  /** 배열 원소가 객체인지 본다. 인덱스를 경로에 남긴다. */
  item: (value: unknown, at: string) => Record<string, unknown>
  fail: (detail: string) => ApiError
}

export function readers(scope: string): Readers {
  const fail = (detail: string) => envelopeError(scope, detail)

  function root(value: unknown, at: string): Record<string, unknown> {
    if (!isRecord(value)) {
      throw fail(`${at}가 객체가 아닙니다`)
    }
    return value
  }

  function rootArray(value: unknown, at: string): unknown[] {
    if (!Array.isArray(value)) {
      throw fail(`${at}가 배열이 아닙니다`)
    }
    return value
  }

  function record(
    source: Record<string, unknown>,
    field: string,
    at: string,
  ): Record<string, unknown> {
    const value = source[field]
    if (!isRecord(value)) {
      throw fail(`${at}.${field}가 객체가 아닙니다`)
    }
    return value
  }

  function array(source: Record<string, unknown>, field: string, at: string): unknown[] {
    const value = source[field]
    if (!Array.isArray(value)) {
      throw fail(`${at}.${field}가 배열이 아닙니다`)
    }
    return value
  }

  function string(source: Record<string, unknown>, field: string, at: string): string {
    const value = source[field]
    if (typeof value !== 'string') {
      throw fail(`${at}.${field}가 문자열이 아닙니다`)
    }
    return value
  }

  /**
   * `Number.isFinite`로 보는 이유는 `NaN`·`Infinity`가 `typeof 'number'`를 통과하기
   * 때문이다. 둘 다 막대 길이 계산에 들어가면 화면이 조용히 깨진다.
   */
  function number(source: Record<string, unknown>, field: string, at: string): number {
    const value = source[field]
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw fail(`${at}.${field}가 유한한 수가 아닙니다`)
    }
    return value
  }

  function boolean(source: Record<string, unknown>, field: string, at: string): boolean {
    const value = source[field]
    if (typeof value !== 'boolean') {
      throw fail(`${at}.${field}가 boolean이 아닙니다`)
    }
    return value
  }

  function nullableString(
    source: Record<string, unknown>,
    field: string,
    at: string,
  ): string | null {
    const value = source[field]
    if (value === null) {
      return null
    }
    if (typeof value !== 'string') {
      throw fail(`${at}.${field}가 문자열 또는 null이 아닙니다`)
    }
    return value
  }

  function nullableNumber(
    source: Record<string, unknown>,
    field: string,
    at: string,
  ): number | null {
    const value = source[field]
    if (value === null) {
      return null
    }
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw fail(`${at}.${field}가 유한한 수 또는 null이 아닙니다`)
    }
    return value
  }

  function readEnum<T extends string>(
    source: Record<string, unknown>,
    field: string,
    at: string,
    allowed: readonly T[],
  ): T {
    const value = string(source, field, at)
    if (!(allowed as readonly string[]).includes(value)) {
      throw fail(`${at}.${field}가 허용 값이 아닙니다: ${value}`)
    }
    return value as T
  }

  function nullableEnum<T extends string>(
    source: Record<string, unknown>,
    field: string,
    at: string,
    allowed: readonly T[],
  ): T | null {
    if (source[field] === null) {
      return null
    }
    return readEnum(source, field, at, allowed)
  }

  function item(value: unknown, at: string): Record<string, unknown> {
    if (!isRecord(value)) {
      throw fail(`${at}가 객체가 아닙니다`)
    }
    return value
  }

  return {
    root,
    rootArray,
    record,
    array,
    string,
    number,
    boolean,
    nullableString,
    nullableNumber,
    enum: readEnum,
    nullableEnum,
    item,
    fail,
  }
}
