/**
 * 배지 표기 테이블 조회.
 *
 * TypeScript는 enum 밖의 값을 컴파일 시점에 막지만 API 응답은 런타임 값이다.
 * 백엔드가 상태값을 추가하면 그대로 들어오므로, 없는 값은 렌더하지 않고 개발 중에만
 * 경고한다. 임의 문자열을 배지로 만들지 않는다는 규칙(설계 §5-2)과 같은 방향이다.
 *
 * 컴포넌트 파일에 두지 않는 이유: 컴포넌트만 export하는 파일이어야 Fast Refresh가 동작한다.
 */
export function lookupLabel<K extends string, V>(
  table: Readonly<Record<K, V>>,
  key: K,
  componentName: string,
): V | undefined {
  if (Object.hasOwn(table, key)) {
    return table[key]
  }
  if (import.meta.env.DEV) {
    console.warn(`[${componentName}] 정의되지 않은 값이 들어왔습니다: ${String(key)}`)
  }
  return undefined
}
