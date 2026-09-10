import { Link, useParams } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Evidence 상세 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `09 Evidence Detail`).
 *
 * v2 구조: 목록 복귀 링크 → hero → Level 2칸(Personal / Repository) →
 * `956/372` split(근거 표 | 다음 Level 안내) → 각주.
 *
 * 근거 표는 v2의 다섯 열을 그대로 쓴다.
 *   유형 / 파일 · 위치 / LEVEL 기여 / 기여자 / GitHub 이동  (52 · 436 · 150 · 130 · 70)
 *
 * v2는 표를 두 그룹으로 나눈다. `Personal Level에 반영된 Evidence`와
 * `Repository Level에만 반영된 Evidence`(타인 Commit → Personal 미반영)다.
 * 이 구분이 이 화면의 핵심이라 그룹 자리를 남기되, 몇 건인지는 API가 준다.
 *
 * 특정 기술의 판정 기준(예: Producer 구현 여부)은 기술마다 달라 하드코딩하지 않는다.
 * `techId`는 실제 route state지만 그것만으로 기술명을 만들 수 없어 제목에 쓰지 않는다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-138(이윤서)에 있다. 시각 적용까지만 한다.
 */
const PROOF_COLUMNS = ['유형', '파일 · 위치', 'LEVEL 기여', '기여자', ''] as const
const PROOF_TEMPLATE = '52px minmax(0,436fr) 150px 130px 70px'

export function EvidenceDetailPage() {
  const { techId } = useParams()

  return (
    <div>
      <Link
        to="/evidence"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 내 기술 목록
      </Link>

      <div className="mt-3">
        <PageHero
          eyebrow="EVIDENCE DETAIL"
          title="이 기술의 판정 근거"
          description="어떤 파일과 Commit으로 판정했는지, 어떤 근거가 Personal Level에 반영됐는지 보여줍니다. 코드 원문은 저장하지 않고 GitHub Permalink로만 연결합니다."
        />
      </div>

      {/* v2는 두 Level을 먼저 나란히 대비시킨다. 값은 판정 결과라 비운다. */}
      <div className="mt-6 grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:max-w-[640px]">
        {[
          { label: 'PERSONAL', caption: '본인 Commit 기준' },
          { label: 'REPOSITORY', caption: '저장소 전체 기준' },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-[14px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
          >
            <p className="text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint">
              {item.label}
            </p>
            <p className="mt-2 text-[15px] font-[750] text-brand-faint">판정 후 표시</p>
            <p className="mt-1 text-[12.5px] text-brand-faint">{item.caption}</p>
          </div>
        ))}
      </div>

      <div className="gj-split mt-4">
        <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <div
            className="hidden gap-4 border-b border-brand-line px-[22px] py-3 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
            style={{ gridTemplateColumns: PROOF_TEMPLATE }}
          >
            {PROOF_COLUMNS.map((label, index) => (
              <span key={label === '' ? `col-${index}` : label} className="truncate">
                {label}
              </span>
            ))}
          </div>
          <div className="p-4">
            <StateCard
              kind="PREPARING"
              title="근거를 아직 불러올 수 없어요"
              description="근거를 돌려주는 조회 API가 준비되면 이 표에 채워집니다. Personal Level에 반영된 근거와 저장소에만 있는 근거를 구분해 보여줍니다."
            />
          </div>
        </div>

        <DataRegion
          eyebrow="NEXT LEVEL"
          title="다음 Level 판정 기준"
          hint="어떤 근거가 더 확인되면 Level이 올라가는지 표시됩니다."
        >
          <StateCard
            kind="PREPARING"
            title="판정 기준 준비 중"
            description="기준은 기술마다 달라 등급 정책과 조회 API가 준비된 뒤 표시합니다. 화면에서 만들어내지 않습니다."
          />
        </DataRegion>
      </div>

      <PageFootnote>
        Raw Code Viewer는 제공하지 않습니다. 각 근거는 GitHub Permalink로 원문을 확인합니다.
        {techId !== undefined && (
          <>
            {' · '}
            기술 <span className="font-evidence text-brand-muted">{techId}</span>
          </>
        )}
      </PageFootnote>
    </div>
  )
}
