import type { EmptySourceJudgement } from '@/features/trend/model/sourceStatus'

/**
 * GitHub 트렌드 카드가 쓰는 판정 보조 · 티켓 S15P21E102-345 / -346.
 *
 * <h2>조회할 기술은 여기서 정하지 않는다</h2>
 *
 * -345 에서는 이 파일이 기술 열 개를 들고 있었다. 그러면 카드가 보여 주는 것은 "이
 * 기간에 많이 관측된 기술"이 아니라 "우리가 고른 열 개 중의 순위"가 된다. 다른
 * 질문이고, 기간이 바뀌어도 기술 종류가 바뀌지 않는다.
 *
 * -346 이 순위 API 를 열면서 그 목록은 사라졌다. 서버가 Registry 전체를 놓고 정렬한
 * 결과를 주고, 화면은 그것을 그대로 그린다.
 */

/**
 * 아직 조회가 끝나지 않은 원천의 상태.
 *
 * 조회 중에 "데이터 없음"을 적으면 아직 모르는 것을 없다고 말하는 것이 된다. 카드는
 * 사라지지 않고 자리를 지키되, 안에서 준비 중이라고만 말한다.
 */
export function pendingSourceStatus(): EmptySourceJudgement & { basis: string } {
  return {
    status: 'PREPARING',
    scopeNote: '이 출처의 데이터를 불러오는 중입니다.',
    // 아직 묻는 중이다. "조회 불가"라고 적으면 카드가 사실과 다른 말을 한다.
    basis: '불러오는 중',
  }
}
