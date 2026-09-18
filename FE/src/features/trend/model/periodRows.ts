import type { TechnologyTrendDto, TrendCompareRowDto } from '@/features/trend/api/trendApi'
import type { TrendSourceId } from '@/features/trend/model/view'
import type { DataStatus } from '@/shared/types/domain'

/**
 * 기술별 상세 상답을 기간별 비교 행으로 묶는다 · 티켓 S15P21E102-329.
 *
 * <h2>왜 이 단계가 따로 있는가</h2>
 *
 * `/trends/compare`는 기술당 한 줄, 그것도 BE가 `points.getLast()`로 고른 마지막 기간만
 * 준다. 개요 카드가 기간을 이동하려면 기간별 값이 있어야 하고, 그것을 주는 것은 기술별
 * 상세 상답의 `points`다. 여기서 하는 일은 그 point들을 `(원천, 기간)`으로 다시 묶어
 * compare가 주던 것과 같은 모양의 행으로 만드는 것뿐이다.
 *
 * <h2>순수 함수로 둔 이유</h2>
 *
 * 타입만 import한다. `node --test`는 `@/` alias를 해석하지 못하므로, 런타임 import가
 * 있는 모듈은 테스트에서 불러올 수 없다. 기간 묶음은 이 화면에서 새로 생긴 유일한
 * 로직이라 테스트로 고정해 둘 값이 있고, 그래서 뷰 조립(`buildSourceView`)과 분리했다.
 *
 * <h2>지어내지 않는 것</h2>
 *
 * 기간 목록은 상답에 실제로 있는 point의 합집합이다. 어떤 기술에도 없는 기간은 목록에
 * 들어오지 않는다. 값이 `null`인 point는 버리지 않고 남긴다 — 그 기간에 그 기술을
 * 관측하지 못했다는 것도 사실이고, 순위에서 빼는 판단은 `rankObservableRows`가 한다.
 *
 * `dataStatus`는 기술·원천 단위 값을 그대로 옮긴다. compare의 행도 같은 값을 썼고,
 * 기준을 바꾸면 같은 기간이 어느 요청으로 왔는지에 따라 달라 보인다(티켓 -327).
 *
 * <h2>point가 없어도 판정은 남긴다</h2>
 *
 * 준비 중·실패는 오류가 아니라 200 + `dataStatus`로 온다. 그래서 point가 하나도 없는
 * 원천에도 서버가 내린 판정이 있고, 그것을 여기서 버리면 화면은 이유를 모른 채
 * "데이터 없음"밖에 말할 수 없다. `judgements`가 그 값이다.
 *
 * 판정을 하나로 줄이는 일은 `model/sourceStatus`가 한다. 이 모듈이 그것을 런타임
 * import하면 `node --test`가 읽지 못하므로(`@/` alias) 여기서는 옮기기만 한다.
 */

/** 한 원천의 기간 목록과 기간별 행. 기간은 오름순이고 마지막이 제일 최신이다. */
export interface TrendPeriodRows {
  periods: string[]
  unit: string | null
  /**
   * 서버가 이 원천에 대해 기술별로 내린 판정. point가 없어도 남는다.
   *
   * **point가 있는 카드의 상태는 이 값이 아니다.** 그쪽은 `buildSourceView`가 기간별
   * 행에서 따로 판정하며, 그것이 티켓 -327이 고정한 경로다. 이 목록은 그릴 기간이
   * 하나도 없을 때 화면이 이유를 말하기 위한 것이다.
   */
  judgements: SourceJudgement[]
  rowsByPeriod: Map<string, TrendCompareRowDto[]>
}

export interface SourceJudgement {
  techId: string
  status: DataStatus
  statusReason: string
}

/** 화면이 그리는 원천만 남긴다. 모르는 원천은 통째로 버린다. */
const SOURCE_IDS: readonly TrendSourceId[] = ['GITHUB_WEEKLY', 'GITHUB_ARCHIVE', 'JOB']

function asSourceId(value: string): TrendSourceId | null {
  return SOURCE_IDS.includes(value as TrendSourceId) ? (value as TrendSourceId) : null
}

export function groupTrendRowsByPeriod(
  dtos: readonly TechnologyTrendDto[],
): Map<TrendSourceId, TrendPeriodRows> {
  const grouped = new Map<TrendSourceId, TrendPeriodRows>()

  for (const dto of dtos) {
    for (const source of dto.sources) {
      const id = asSourceId(source.sourceId)
      if (id === null) {
        continue
      }
      const fresh: TrendPeriodRows = {
        periods: [],
        unit: source.unit,
        judgements: [],
        rowsByPeriod: new Map(),
      }
      const entry = grouped.get(id) ?? fresh
      entry.judgements.push({
        techId: dto.techId,
        status: source.dataStatus,
        statusReason: source.statusReason,
      })
      for (const pointItem of source.points) {
        const bucket = entry.rowsByPeriod.get(pointItem.period) ?? []
        bucket.push({
          techId: dto.techId,
          dataStatus: source.dataStatus,
          statusReason: source.statusReason,
          period: pointItem.period,
          value: pointItem.value,
          ratio: pointItem.ratio,
          absoluteChange: pointItem.absoluteChange,
          relativeChange: pointItem.relativeChange,
        })
        entry.rowsByPeriod.set(pointItem.period, bucket)
      }
      grouped.set(id, entry)
    }
  }

  for (const entry of grouped.values()) {
    entry.periods = [...entry.rowsByPeriod.keys()].sort()
  }
  return grouped
}
