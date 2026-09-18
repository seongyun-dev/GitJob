const INTERNAL_RULE_CODE = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/

const SUMMARY_FALLBACK = '확인된 파일과 사용 위치를 아래 근거 목록에서 확인해 보세요.'

/** AI 응답에 내부 규칙명이 섞이면 노출하지 않고, 한글 날짜 간격만 자연스럽게 다듬는다. */
export function evidenceSummaryText(value: string): string {
  if (INTERNAL_RULE_CODE.test(value)) return SUMMARY_FALLBACK

  return value
    .replace(/(\d{4})\s*년\s*/g, '$1년 ')
    .replace(/(\d{1,2})\s*월/g, '$1월')
    .replace(/(\d{1,2})\s*일/g, '$1일')
}

/** 부족한 규칙의 원문은 구현 세부라 숨기고, 사용자가 확인할 다음 위치만 안내한다. */
export function missingEvidenceGuide(gap: string | null): string | null {
  return gap === null
    ? null
    : '아직 확인되지 않은 사용 형태가 있어요. 아래 근거 목록에서 확인된 범위를 살펴보세요.'
}
