import { Link, useParams } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 추천 기술 상세 · 티켓 S15P21E102-204
 * (확정 디자인 `Final v2`의 `11 Recommended Technology Detail`).
 *
 * v2 구조: hero(+Personal / Target / What-if 3축) → `956/372` split →
 * 번호가 붙은 근거 섹션(`120 / 754`) → 각주.
 *
 * v2는 상단에 `추천 근거 · 프로젝트 · FAQ / Pain · Trend` 탭을 둔다. 전환할 데이터가
 * 없어 **탭으로 만들지 않는다.** 대신 각 갈래가 무엇을 담는지 정적으로 밝혀 둔다.
 * 누를 수 있는데 아무 일도 없는 컨트롤을 만들지 않는다.
 *
 * `Personal L1` · `Target L2` · `What-if +15`, `31 / 87건` 같은 값은 전부 C조 계산
 * 결과이고 조회 API가 develop에 없다. FE가 만들지 않는다.
 */
const AXES = [
  { label: 'Personal', note: '분석 후 표시', caption: '본인 Commit으로 확인된 Level' },
  { label: 'Target', note: '계산 후 표시', caption: '다음 판정 단계' },
  { label: 'What-if', note: '계산 후 표시', caption: '확보 시 새로 충족되는 공고 수' },
] as const

/** v2가 나누는 근거 갈래. 이름은 제품 정의라 값 없이도 보여줄 수 있다. */
const SECTIONS = [
  {
    no: '01',
    title: '현재 상태',
    hint: '지금 확인된 Level과 그 근거 파일, Personal과 Repository가 다른 이유',
  },
  {
    no: '02',
    title: '왜 필요한가',
    hint: '비교 중인 공고에서 얼마나 요구되는지, 선행 기술은 충족했는지',
  },
  {
    no: '03',
    title: '무엇을 만들면 되나',
    hint: '어떤 구현이 있으면 다음 Level 근거가 되는지',
  },
  {
    no: '04',
    title: 'FAQ · 자주 막히는 지점',
    hint: '학습·구현에서 자주 나오는 어려움과 참고 자료',
  },
] as const

export function TechnologyDetailPage() {
  const { techId } = useParams()

  return (
    <div>
      <Link
        to="/recommendations"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 다음 학습 기술
      </Link>

      <div className="mt-3">
        <PageHero
          eyebrow="RECOMMENDED TECHNOLOGY"
          title="이 기술을 왜 추천했나요"
          description="어떤 순서로 익히고 무엇을 만들면 Evidence를 남길 수 있는지 안내합니다. 학습 안내는 근거를 남기는 방법을 보여주는 것이지 점수를 올리는 방법이 아닙니다."
        />
      </div>

      <div className="mt-6">
        <StatStrip items={AXES} />
      </div>

      <div className="gj-split mt-4">
        <div className="grid gap-4">
          {SECTIONS.map((section) => (
            <DataRegion
              key={section.no}
              eyebrow={section.no}
              title={section.title}
              hint={section.hint}
            >
              <StateCard
                kind="PREPARING"
                title="준비 중"
                description="추천 근거와 학습 가이드를 돌려주는 조회 API가 준비되면 이 자리에 표시합니다."
              />
            </DataRegion>
          ))}
        </div>

        <div className="grid gap-4">
          <DataRegion
            eyebrow="TREND"
            title="이 기술의 트렌드"
            hint="출처별 추이는 별도 화면에서 봅니다."
          >
            <Link
              to={techId === undefined ? '/trends' : `/trends/${techId}`}
              className="block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              이 기술의 트렌드 보기
            </Link>
          </DataRegion>

          <DataRegion
            eyebrow="EVIDENCE"
            title="지금 내 근거"
            hint="이 기술로 확인된 파일과 Commit을 확인합니다."
          >
            <Link
              to={techId === undefined ? '/evidence' : `/evidence/${techId}`}
              className="block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              근거 상세 보기
            </Link>
          </DataRegion>
        </div>
      </div>

      <PageFootnote>
        Level은 숙련도 점수가 아니라 근거의 누적 상태입니다. 학습 안내는 근거를 남기는 방법을
        보여주는 것이지 점수를 올리는 방법이 아닙니다.
      </PageFootnote>
    </div>
  )
}
