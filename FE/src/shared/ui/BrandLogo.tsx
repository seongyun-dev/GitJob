import logoUrl from '@/assets/gitjob-logo.png'

/**
 * 브랜드 로고 · Final v2에서 도입.
 *
 * v1은 헤더마다 `G` 한 글자를 둥근 사각형에 넣어 로고를 대신했다. Final v2는
 * 17개 아트보드 전부가 실제 로고 이미지를 쓴다. 표시 높이만 화면마다 달라
 * 여기로 모은다.
 *
 *   랜딩 36px · 연결 화면 30px · 앱 헤더 26px
 *
 * 높이를 props가 아니라 `className`으로 받는다. 랜딩은 헤더가 88px에서 72px로
 * 접히면서 로고도 함께 줄어야 해서 숫자 하나로는 부족하다.
 *
 * 원본이 1362x420 PNG(318KB)다. 표시 높이의 10배가 넘어 파일이 무겁다.
 * TODO: 디자이너에게 SVG를 받아 교체한다. 워드마크는 벡터가 맞다.
 *
 * 심볼 단독(`gitjob-symbol.png`)은 넣지 않았다. Final v2에서 그 이미지를 쓰는
 * 자리는 로그인 화면 카드 중앙뿐이고 그 화면은 아직 없다. 쓰지 않는 이미지를
 * import 하면 번들에 128KB가 그대로 실린다.
 */
export function BrandLogo({ className }: { className?: string }) {
  return <img src={logoUrl} alt="GitJob" className={`block w-auto ${className ?? ''}`} />
}
