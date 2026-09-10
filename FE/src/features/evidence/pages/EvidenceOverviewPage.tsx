import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatShell, TableScaffold } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Final `#evidence` 표의 컬럼과 열 폭. computed style에서 그대로 읽었다.
 * 마지막 120px는 상세 링크 자리다. 링크는 대상 기술이 있어야 만들 수 있어 지금은 비운다.
 */
const EVIDENCE_COLUMNS = ['기술', 'PERSONAL', 'REPOSITORY', '대표 EVIDENCE', ''] as const
const EVIDENCE_TEMPLATE = '1.2fr .7fr .7fr 1.6fr 120px'

/**
 * Evidence Overview 초안 · 티켓 S15P21E102-192 (세부 기능은 S15P21E102-137).
 *
 * 시각 기준: Final `section#evidence` — hero → 지표 행(`299px x 4`) → 기술별 판정
 * 목록 → 각주. 카드 한 줄이 아니라 영역 두 개와 각주로 구성된다.
 *
 * 기술 목록과 Level을 표시하지 않는다. Evidence 결과 목록 API가 develop에 없고
 * (BE `S15P21E102-134` 미구현) Evidence 관련 Controller·DTO·Entity가 하나도 없다.
 * Level 판정은 C조 몫이라 FE가 계산하지 않는다.
 *
 * 계약 공백이 하나 더 있다. 확정 정책은 "저장소마다 별도 analysisId, 기술별 최고
 * Level 채택"인데 C조 `EvidenceAnalysis`는 `analysis_id` 하나에 `repositories[N]`
 * 구조다. 여러 analysisId를 가로지르는 집계 단위가 계약에 없다.
 */
export function EvidenceOverviewPage() {
  return (
    <div>
      <PageHero
        eyebrow="MY EVIDENCE"
        title="내 GitHub에서 확인된 기술"
        description="Evidence는 점수가 아니라 근거입니다. 의존성 선언, 소스 코드 사용, Commit 작성자를 근거로 판정하고 파일과 라인까지 확인할 수 있습니다."
      />

      {/*
        지표 행. Final은 hero 바로 아래 `repeat(4,1fr)`로 네 지표를 둔다.
        값은 없지만 라벨과 기준은 제품 정의라 지금 보여줄 수 있다. 값 자리를 `0`이나
        `-`로 채우지 않는다. `0`은 "분석했더니 없었다"는 거짓이 되고 `-`는 무엇을
        기다리는지 알려주지 않는다.
      */}
      <div className="gj-stats mt-7">
        <StatShell label="확인된 기술" note="분석 후 표시" caption="Personal Evidence 기준" />
        <StatShell label="L2 이상" note="분석 후 표시" caption="Personal Level 기준" />
        <StatShell label="분석한 Repository" note="분석 후 표시" caption="선택한 저장소 기준" />
        <StatShell label="마지막 분석" note="기록 없음" caption="분석을 실행하면 기록됩니다" />
      </div>

      <div className="mt-4 grid gap-4">
        <DataRegion
          eyebrow="TECHNOLOGY"
          title="기술별 판정"
          hint="Personal Level은 본인 Commit이 확인된 범위, Repository Level은 저장소 전체 기준입니다."
        >
          {/*
            표의 컬럼 헤더는 남기고 행만 비운다. 헤더가 있으면 무엇이 들어올 자리인지
            읽히고, 없으면 화면이 미완성으로 보인다(2026-09-10 Design Audit).
            가짜 기술 행은 만들지 않는다.
          */}
          <TableScaffold columns={EVIDENCE_COLUMNS} template={EVIDENCE_TEMPLATE}>
            <StateCard
              kind="PREPARING"
              title="판정 결과를 아직 불러올 수 없어요"
              description="기술별 판정을 돌려주는 조회 API가 준비되면 이 표에 채워집니다. 추정값으로 채우지 않습니다."
            />
          </TableScaffold>
        </DataRegion>

        <div className="gj-duo">
          <DataRegion
            eyebrow="INSUFFICIENT"
            title="근거가 부족한 기술"
            hint="선언만 확인된 기술은 Level을 판정하지 않습니다."
          >
            <StateCard
              kind="INSUFFICIENT_DATA"
              title="판정하지 않은 기술이 모이는 자리"
              description="Dependency 선언만 확인되면 Level을 판정하지 않고 그 사실을 그대로 표시합니다."
            />
          </DataRegion>

          <DataRegion
            eyebrow="SCOPE"
            title="판정 범위"
            hint="분석에 포함된 저장소와 제외 사유가 표시됩니다."
          >
            <StateCard
              kind="NO_DATA"
              title="아직 분석한 저장소가 없어요"
              description="저장소를 선택해 분석하면 어떤 저장소가 어떤 기술의 근거가 됐는지 여기에서 확인할 수 있습니다."
            />
          </DataRegion>
        </div>
      </div>

      <PageFootnote>
        Personal Level이 Repository Level보다 낮은 기술은 저장소에는 구현이 있으나 본인 기여
        근거가 확인되지 않은 경우입니다. 점수로 환산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
