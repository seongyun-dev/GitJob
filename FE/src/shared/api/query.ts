/**
 * 쿼리 문자열 조립 · 티켓 S15P21E102-281.
 *
 * 빈 값을 뺀 쿼리 문자열을 만든다. 조회 파라미터가 대부분 optional이고 기본값을
 * **서버가** 정하므로, 지정하지 않은 값은 보내지 않는다. FE가 기본값을 만들어 보내면
 * 서버 기본값이 바뀔 때 두 곳이 어긋난다.
 *
 * `features/evidence/api/evidenceApi.ts`가 같은 함수를 비공개로 두고 있다. 281이
 * 세 기능(matching·trend·technology)에서 같은 것을 쓰게 되어 여기로 옮긴다 —
 * 그쪽 사본은 검증된 코드라 이 티켓에서 건드리지 않았다.
 */
export function toQuery(params: Record<string, string | number | boolean | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      query.set(key, String(value))
    }
  }
  const serialized = query.toString()
  return serialized === '' ? '' : `?${serialized}`
}
