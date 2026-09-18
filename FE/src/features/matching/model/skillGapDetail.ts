import type { SkillGapRowView, SkillGapVerdict } from '@/features/matching/model/view'

/**
 * Skill Gap 지표 네 칸이 각각 센 대상 · 화면 17.
 *
 * 지표는 숫자 하나라 "어떤 기술이 그렇게 세어졌는지"를 말하지 못한다. `내 기술`
 * 화면(`08 My Evidence`)이 지표를 눌러 목록을 여는 것과 같은 규칙으로, 여기서도
 * 각 지표가 **caption과 같은 기준**으로 고른 행을 그대로 펼친다.
 *
 * 합계는 여전히 서버 값(`summary`)이고 여기서 다시 세지 않는다. 이 목록은 숫자를
 * 만드는 자리가 아니라 그 숫자의 근거를 보여주는 자리다. 서버 합과 행 수가 어긋나면
 * 그 사실이 목록에서 드러나는 것이 맞다.
 */
export type SkillGapStatDetail = 'required' | 'met' | 'gap' | 'undetermined'

/**
 * `부족`은 두 판정의 합이다. `판단 근거 부족`은 그 합에 넣지 않는다 -- 평가하지 않은
 * 기술을 부족으로 보이게 하는 것이 이 화면이 가장 피하는 오독이다.
 */
const DETAIL_VERDICTS: Readonly<Record<SkillGapStatDetail, readonly SkillGapVerdict[]>> = {
  required: ['MET', 'LEVEL_SHORT', 'NO_EVIDENCE', 'UNDETERMINED'],
  met: ['MET'],
  gap: ['LEVEL_SHORT', 'NO_EVIDENCE'],
  undetermined: ['UNDETERMINED'],
}

export const SKILL_GAP_DETAIL_TEXT: Readonly<
  Record<SkillGapStatDetail, { title: string; description: string }>
> = {
  required: {
    title: '요구 기술',
    description: '비교 집합의 공고가 필수 또는 우대로 1건 이상 언급한 기술입니다.',
  },
  met: { title: '충족한 기술', description: '공고가 요구하는 Level 이상을 보유한 기술입니다.' },
  gap: {
    title: '부족한 기술',
    description: '미보유이거나 근거는 있지만 요구 Level에 미치지 못하는 기술입니다.',
  },
  undetermined: {
    title: '판단 근거 부족',
    description: '평가하지 않은 기술입니다. 부족으로 세지 않습니다.',
  },
}

/** 지표 하나가 센 행. 표의 묶음 순서(판정 순)를 그대로 따라간다. */
export function skillGapDetailRows(
  rows: readonly SkillGapRowView[],
  detail: SkillGapStatDetail,
): SkillGapRowView[] {
  const verdicts = DETAIL_VERDICTS[detail]
  return rows.filter((row) => verdicts.includes(row.verdict))
}
