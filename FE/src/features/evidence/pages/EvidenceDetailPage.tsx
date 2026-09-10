import { Link, useParams } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatShell, TableScaffold } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/** Final `#evdetail` 근거 표의 컬럼. 유형 · 위치 · 근거 · 범위 · Level 순이다. */
const PROOF_COLUMNS = ['유형', '위치', '근거', '범위', 'LEVEL'] as const
const PROOF_TEMPLATE = '80px 1.4fr 1.6fr 1fr 80px'

/**
 * Evidence Detail 초안 · 티켓 S15P21E102-192 (세부 기능은 S15P21E102-138).
 *
 * 시각 기준: Final `section#evdetail` — hero → `846 372` split. 근거 목록이 본문이고
 * 판정 기준이 우측 패널이다.
 *
 * 파일 경로·라인·Commit을 표시하지 않는다. Evidence 상세 조회 API가 develop에 없다
 * (BE `S15P21E102-135` 미구현). 근거 행은 permalink가 없으면 렌더하지 않는다는 규칙
 * (`shared/ui/EvidenceRow`)이 이미 있어 없는 근거를 만들어 보여줄 수 없다.
 *
 * URL의 `techId`는 실제 경로 파라미터다. 기술명이 API에서 오기 전까지 식별자를 쓴다.
 */
export function EvidenceDetailPage() {
  const { techId } = useParams()

  return (
    <div>
      <PageHero
        eyebrow="EVIDENCE DETAIL"
        title={techId ?? '기술 상세'}
        description="이 기술을 어떤 파일과 Commit으로 판정했는지, 어떤 규칙이 충족되고 무엇이 부족한지 확인할 수 있습니다."
      />

      {/* Final `#evdetail`은 두 Level을 먼저 대비시킨다. 값은 판정 결과라 비운다. */}
      <div className="gj-duo mt-7">
        <StatShell label="Personal Level" note="판정 후 표시" caption="본인 Commit으로 확인된 범위" />
        <StatShell label="Repository Level" note="판정 후 표시" caption="저장소 전체 기준" />
      </div>

      <div className="gj-split mt-4">
        <div className="grid gap-4">
          <DataRegion
            eyebrow="PROOF"
            title="판정 근거"
            hint="저장소 · 파일 경로 · 코드 위치 · 탐지 규칙 순으로 표시됩니다."
          >
            {/*
              Final `#evdetail`은 근거를 표로 세운다(유형 · 위치 · 근거 · 범위 · Level).
              컬럼은 제품 정의라 지금 보여줄 수 있고, 행은 조회 API가 있어야 만들 수 있다.
              특정 기술의 판정 기준(예: Producer 구현 여부)은 기술마다 달라 하드코딩하지 않는다.
            */}
            <TableScaffold columns={PROOF_COLUMNS} template={PROOF_TEMPLATE}>
              <StateCard
                kind="PREPARING"
                title="판정 근거를 아직 불러올 수 없어요"
                description="근거를 돌려주는 조회 API가 준비되면 파일과 라인까지 그대로 보여줍니다. GitHub 링크도 함께 제공됩니다."
              />
            </TableScaffold>
          </DataRegion>

          <DataRegion
            eyebrow="CONTRIBUTION"
            title="본인 기여 판정"
            hint="Commit 작성자를 기준으로 본인 기여 여부와 그 이유가 표시됩니다."
          >
            <StateCard
              kind="PREPARING"
              title="기여 판정 준비 중"
              description="기여 비율은 제공하지 않습니다. 주 작성자 · 공동 작업 · 일부 수정 같은 구분만 표시합니다."
            />
          </DataRegion>
        </div>

        <aside className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">LEVEL</p>
          <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            판정 기준
          </h2>
          <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-muted">
            L0부터 L3까지는 숙련도가 아니라 근거의 누적 상태입니다.
          </p>
          <dl className="mt-4 grid gap-2.5">
            <div>
              <dt className="text-[13px] font-semibold text-brand-ink">의존성 선언</dt>
              <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                manifest · lockfile · SBOM
              </dd>
            </div>
            <div>
              <dt className="text-[13px] font-semibold text-brand-ink">사용 코드</dt>
              <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                source · config · test
              </dd>
            </div>
            <div>
              <dt className="text-[13px] font-semibold text-brand-ink">본인 기여</dt>
              <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                Commit 작성자 기준
              </dd>
            </div>
          </dl>
          <Link
            to="/evidence"
            className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            기술 목록으로
          </Link>
          {techId !== undefined && (
            <Link
              to={`/technologies/${techId}`}
              className="mt-2 block rounded-xl px-4 py-2.5 text-center text-[13px] text-brand-muted hover:text-brand-ink"
            >
              이 기술 학습 안내
            </Link>
          )}
        </aside>
      </div>

      <PageFootnote>
        근거 없는 판정 행은 표시하지 않습니다. 데이터가 부족하면 Level을 비우고 그 사실을
        그대로 밝힙니다.
      </PageFootnote>
    </div>
  )
}
