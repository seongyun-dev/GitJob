import { Link, useParams } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Final `#analysis`가 정의한 분석 4단계. 이름은 제품이 무엇을 하는지에 대한 정의라
 * 데이터가 없어도 보여줄 수 있다. **완료 여부·처리 건수·퍼센트는 넣지 않는다.**
 * Final의 `✓`와 `1,284개 파일`은 조회 API가 있어야 알 수 있는 값이다.
 */
const ANALYSIS_STEPS = [
  { name: '저장소 확인', detail: '분석 대상 Repository와 기본 브랜치 확인' },
  { name: '파일 구조 분석', detail: '빌드 설정 · 의존성 선언 · 소스 트리 파싱' },
  { name: 'Evidence 판정', detail: '기술별 사용 근거와 Level 판정' },
  { name: '사용자 기여 확인', detail: 'Commit 작성자 대조로 본인 기여 구분' },
] as const

/**
 * Analysis Progress 초안 · 티켓 S15P21E102-192 (세부 기능은 S15P21E102-136).
 *
 * 시각 기준: Final `section#analysis` — hero → `846 372` split(진행 영역 | 우측 패널).
 *
 * 진행률을 표시하지 않는다. 상태 조회 API(`GET /api/v1/analyses/{analysisId}`)가
 * develop에 없어서(BE `S15P21E102-133` 미구현) 단계·처리 대상 수·남은 시간을 알
 * 방법이 없다. Final은 `72%`와 `약 1분 남음`을 보여주지만 그 숫자를 만들어내면
 * fake data다.
 *
 * URL의 `analysisId`는 실제 값이다. 저장소 선택 화면이 `POST /api/v1/analyses`로
 * 받은 ID이므로 그대로 보여준다.
 */
export function AnalysisProgressPage() {
  const { analysisId } = useParams()

  return (
    <div>
      <PageHero
        eyebrow="ANALYSIS"
        title="GitHub를 분석하고 있어요"
        description="Repository마다 독립적으로 분석하며 분석 ID도 저장소별로 따로 생깁니다. 분석이 끝나면 기술별 Evidence를 확인할 수 있습니다."
      />

      <div className="gj-split mt-7">
        <div className="grid gap-4">
          <DataRegion
            eyebrow="PROGRESS"
            title="분석 진행"
            hint="현재 단계와 저장소별 완료 여부가 이 자리에 들어갑니다."
          >
            {/*
              단계 목록. Final은 각 단계에 `✓`와 처리 건수를 붙이지만 그건 조회 API가
              있어야 아는 값이다. 여기서는 단계 이름과 하는 일만 세우고, 어디까지
              진행됐는지는 아래 상태 카드가 "아직 알 수 없다"고 밝힌다.
            */}
            <ol className="grid gap-2.5">
              {ANALYSIS_STEPS.map((step, index) => (
                <li
                  key={step.name}
                  className="flex items-start gap-3 rounded-[14px] border border-brand-line bg-white/70 px-4 py-3"
                >
                  <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-tone-neutral-bg text-[11px] font-extrabold text-tone-neutral">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">
                      {step.name}
                    </p>
                    <p className="mt-0.5 text-[12.5px] leading-[1.55] text-brand-muted">
                      {step.detail}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
            <div className="mt-3">
              <StateCard
                kind="PREPARING"
                title="진행 상태를 아직 조회할 수 없어요"
                description="어느 단계까지 진행됐는지 돌려주는 조회 API가 준비되면 위 단계에 표시됩니다. 접수된 분석은 서버에서 계속 진행됩니다."
              />
            </div>
          </DataRegion>

        </div>

        <aside className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">NEXT</p>
          <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            다음 단계
          </h2>
          <ol className="mt-4 grid gap-3">
            <li>
              <p className="text-[13px] font-semibold text-brand-ink">기술 Evidence 확인</p>
              <p className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                의존성 · 사용 코드 · Commit 근거로 판정된 기술
              </p>
            </li>
            <li>
              <p className="text-[13px] font-semibold text-brand-ink">공고 요건과 비교</p>
              <p className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                충족된 기술과 부족한 기술 구분
              </p>
            </li>
            <li>
              <p className="text-[13px] font-semibold text-brand-ink">다음 학습 기술</p>
              <p className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                무엇을 채우면 비교 대상이 늘어나는지
              </p>
            </li>
          </ol>
          <Link
            to="/evidence"
            className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            Evidence 화면 보기
          </Link>
          <Link
            to="/onboarding/repositories"
            className="mt-2 block rounded-xl px-4 py-2.5 text-center text-[13px] text-brand-muted hover:text-brand-ink"
          >
            저장소 다시 선택
          </Link>
        </aside>
      </div>

      {/*
        분석 ID는 실제 route state지만 화면의 주요 정보가 아니다. 이전에는 본문
        영역 한 칸을 통째로 차지해 `test` 같은 값이 페이지 콘텐츠처럼 보였고
        디버그 화면 같은 인상을 줬다(2026-09-10 Design Audit). 각주로 내린다.
      */}
      {analysisId !== undefined && (
        <PageFootnote>
          분석 ID <span className="font-evidence text-brand-muted">{analysisId}</span> · 이 화면을
          벗어나도 분석은 서버에서 계속 진행됩니다.
        </PageFootnote>
      )}
    </div>
  )
}
