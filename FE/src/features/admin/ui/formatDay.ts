/**
 * 후보 화면의 날짜 표기.
 *
 * 목록과 드로어가 같은 값을 다르게 쓰면(한쪽은 2026. 9. 16., 다른 쪽은 9/16) 같은
 * 후보를 두 화면에서 볼 때 다른 날로 읽힌다. 한 곳에서 만든다.
 *
 * 시각은 버린다. 관찰이 쌓인 날짜만 판단에 쓰이고, 분 단위는 행을 길게 만들 뿐이다.
 */
export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  })
}
