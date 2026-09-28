import symbolUrl from '@/assets/gitjob-symbol.png'

/**
 * 브랜드 심볼(육각형) 단독 마크.
 *
 * 워드마크({@link BrandLogo})와 달리 글자 없이 심볼만 쓴다. Final v2에서 이 이미지가
 * 필요한 자리는 로그인 화면 카드 중앙이라, 그 화면을 만들면서 함께 도입했다.
 * `gitjob-logo.png`(워드마크)에서 심볼 영역만 잘라낸 것이다.
 *
 * 높이는 {@link BrandLogo}와 같은 이유로 props가 아니라 `className`으로 받는다.
 */
export function BrandSymbol({ className }: { className?: string }) {
  return <img src={symbolUrl} alt="" aria-hidden className={`block w-auto ${className ?? ''}`} />
}
