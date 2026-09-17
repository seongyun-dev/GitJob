import { useState } from 'react'
import { Link } from 'react-router'
import { useJobDemands, useSaveTarget, useTarget } from '@/features/matching/hooks/useMatching'
import { formatCollectedAt } from '@/features/matching/model/presentation'
import { ApiError } from '@/shared/api/client'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { MeterBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 목표 직무 선택 · 확정 디자인 `Final v2`의 `16 Target Role Selection` 재구성
 * (S15P21E102-279).
 *
 * <h2>직무 카드 3열을 쓰지 않는다</h2>
 *
 * v2 아트보드는 직무 카드 셋을 나열하는데, 그 아트보드 자신이 그 영역에
 * `DESIGN MOCK ROLE TAXONOMY`라고 적어 두었다. 확정된 직무 목록은 아직 없고, 목록을
 * 돌려주는 API도 없다. 목록을 화면이 만들면 그 자체가 제품 결정이 되므로, 직무를
 * <b>입력</b>받고 그 직무의 실제 수요를 보여 주는 형태로 둔다.
 *
 * 입력한 직무가 유효한지는 C가 판정한다. 지원하지 않는 직무면 수요 조회가
 * `MATCH-400-1`로 돌아오고, 그 사실이 화면에 그대로 보인다 — 화면이 목록을 복제해
 * 미리 막으면 C가 직무를 늘릴 때마다 FE가 뒤처진다.
 *
 * <h2>왜 저장하는가</h2>
 *
 * 저장소 분석이 끝나는 순간 서버가 이 값으로 계산을 시작한다. 화면 상태로만 두면
 * 브라우저를 닫은 사이에는 계산할 조건이 없다.
 */

/** 폼이 들고 있는 값. 세 칸이 함께 움직여야 저장 시 일부만 반영되는 일이 없다. */
interface Form {
  targetRole: string
  regions: string
  careerLevels: string
}

/** 쉼표로 적은 필터를 목록으로. 빈 값은 "전체"다. */
function toList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '')
}

export function TargetRolePage() {
  const target = useTarget()
  const save = useSaveTarget()

  /*
   * 폼 값은 "사용자가 고친 것"만 담는다. 손대기 전에는 저장된 값을 그대로 보여주고,
   * 한 글자라도 고치면 그때부터 입력이 우선한다.
   *
   * effect로 서버 값을 state에 복사하지 않는 이유가 이것이다. 복사하면 재조회가 돌
   * 때마다 입력 중인 값이 되돌아가고, 무엇보다 "아직 고치지 않음"과 "빈 값으로
   * 고침"을 구분할 수 없게 된다.
   */
  const saved = target.data
  const [draft, setDraft] = useState<Form | null>(null)
  const form: Form = draft ?? {
    targetRole: saved?.targetRole ?? '',
    regions: saved?.regions.join(', ') ?? '',
    careerLevels: saved?.careerLevels.join(', ') ?? '',
  }
  const { targetRole, regions, careerLevels } = form
  const update = (patch: Partial<Form>) => setDraft({ ...form, ...patch })

  // 미리보기는 저장된 직무가 아니라 지금 입력한 직무로 본다. 저장 전에 확인할 수
  // 있어야 잘못된 직무를 저장하지 않는다.
  const preview = useJobDemands({
    targetRole: targetRole.trim() === '' ? undefined : targetRole.trim(),
    regions: toList(regions),
    careerLevels: toList(careerLevels),
  })
  const technologies = preview.data?.technologies ?? []
  const topCount = technologies[0]?.requiredCount ?? 0

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="TARGET ROLE"
          title="어떤 직무 공고와 비교할까요?"
          description="Evidence는 그대로 두고 비교할 공고 집합만 바꿉니다. 직무마다 요구 기술이 달라 같은 Evidence라도 충족 결과가 달라집니다."
        />
        <Link
          to="/evidence"
          className="shrink-0 rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
        >
          ← 내 Evidence
        </Link>
      </div>

      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <form
          className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
          onSubmit={(event) => {
            event.preventDefault()
            save.mutate({
              targetRole: targetRole.trim(),
              regions: toList(regions),
              careerLevels: toList(careerLevels),
            })
          }}
        >
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            비교 조건
          </p>

          <label
            htmlFor="target-role"
            className="mt-4 block text-[12.5px] font-semibold text-brand-ink-soft"
          >
            직무
          </label>
          <input
            id="target-role"
            value={targetRole}
            onChange={(event) => update({ targetRole: event.target.value })}
            placeholder="BACKEND"
            className="mt-1.5 w-full rounded-[10px] border border-brand-line px-3 py-2.5 text-[13px] text-brand-ink"
          />
          <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-faint">
            지원하는 직무인지는 계산 서버가 판정합니다. 아래 미리보기에 수요가 나오면 유효한
            직무입니다.
          </p>

          <label
            htmlFor="target-regions"
            className="mt-4 block text-[12.5px] font-semibold text-brand-ink-soft"
          >
            지역 <span className="font-normal text-brand-faint">· 쉼표로 구분, 비우면 전체</span>
          </label>
          <input
            id="target-regions"
            value={regions}
            onChange={(event) => update({ regions: event.target.value })}
            placeholder="서울"
            className="mt-1.5 w-full rounded-[10px] border border-brand-line px-3 py-2.5 text-[13px] text-brand-ink"
          />

          <label
            htmlFor="target-careers"
            className="mt-4 block text-[12.5px] font-semibold text-brand-ink-soft"
          >
            경력 <span className="font-normal text-brand-faint">· 쉼표로 구분, 비우면 전체</span>
          </label>
          <input
            id="target-careers"
            value={careerLevels}
            onChange={(event) => update({ careerLevels: event.target.value })}
            placeholder="신입"
            className="mt-1.5 w-full rounded-[10px] border border-brand-line px-3 py-2.5 text-[13px] text-brand-ink"
          />

          <button
            type="submit"
            disabled={targetRole.trim() === '' || save.isPending}
            className="mt-5 w-full rounded-[10px] bg-brand-ink px-4 py-3 text-[13.5px] font-[750] text-white disabled:cursor-not-allowed disabled:bg-[#B9C4D6]"
          >
            {save.isPending ? '저장 중…' : '이 조건으로 저장'}
          </button>

          {save.isError && (
            <p className="mt-3 text-[12.5px] leading-[1.6] text-tone-danger">
              {save.error instanceof ApiError
                ? save.error.message
                : '목표 직무를 저장하지 못했습니다.'}
            </p>
          )}
          {save.isSuccess && (
            <p className="mt-3 text-[12.5px] leading-[1.6] text-tone-success">
              저장했습니다. 분석 결과가 있으면 곧 대조 결과가 계산됩니다.
            </p>
          )}

          {/*
            저장된 조건을 함께 보여 준다. 입력 중인 값과 실제로 계산에 쓰이는 값이
            다를 수 있고, 그 차이를 숨기면 사용자는 저장했다고 착각한다.
          */}
          <div className="mt-5 border-t border-brand-line pt-4">
            <p className="text-[12.5px] text-brand-faint">저장된 조건</p>
            <p className="mt-1 text-[13.5px] font-[750] text-brand-ink">
              {saved === null || saved === undefined
                ? '아직 없음'
                : [saved.targetRole, ...saved.regions, ...saved.careerLevels].join(' · ')}
            </p>
          </div>
        </form>

        <DataRegion
          eyebrow="DEMAND PREVIEW"
          title="이 조건의 공고가 요구하는 기술"
          hint="저장하기 전에 확인합니다. 순위와 건수는 계산 서버가 집계한 값이며 화면이 세지 않습니다."
        >
          {targetRole.trim() === '' ? (
            <StateCard
              kind="EMPTY"
              title="직무를 입력하면 수요를 보여드려요"
              description="그 직무의 공고가 어떤 기술을 얼마나 요구하는지 먼저 확인할 수 있습니다."
            />
          ) : (
            <>
              <ComputeStatePanel
                isLoading={preview.isLoading}
                error={preview.error}
                state={preview.data}
                loadingLabel="이 조건의 수요를 불러오는 중입니다."
                onRetry={() => void preview.refetch()}
              />

              {preview.data !== undefined &&
                preview.data.dataStatus === 'READY' &&
                (technologies.length === 0 ? (
                  <StateCard
                    kind="NO_DATA"
                    title="이 조건에는 집계된 수요가 없어요"
                    description="조건을 넓히면 공고 표본이 늘어납니다."
                  />
                ) : (
                  <>
                    <p className="text-[12px] text-brand-faint">
                      비교 대상 공고 {preview.data.basis.jobCount ?? 0}건 ·{' '}
                      {formatCollectedAt(preview.data.basis.asOf)}
                    </p>
                    <ol className="mt-3 grid gap-3">
                      {technologies.map((technology) => (
                        <li key={technology.techId} className="flex items-start gap-3">
                          <span className="mt-0.5 text-[11px] font-extrabold tabular-nums text-brand-faint">
                            {String(technology.rank).padStart(2, '0')}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-baseline justify-between gap-2">
                              <p className="truncate text-[13.5px] font-[750] text-brand-ink">
                                {technology.techId}
                              </p>
                              <span className="shrink-0 text-[12px] tabular-nums text-brand-muted">
                                필수 {technology.requiredCount}건
                              </span>
                            </div>
                            <div className="mt-1.5">
                              {/* 분모는 이 조건의 1위 값이다. 직무 간 비교로 읽히지 않게 한다 */}
                              <MeterBar
                                value={technology.requiredCount}
                                total={topCount}
                                tone={technology.rank === 1 ? 'accent' : 'muted'}
                                height={5}
                              />
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </>
                ))}
            </>
          )}

          <Link
            to="/jobs"
            className="mt-5 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
          >
            공고 매칭 보기
          </Link>
        </DataRegion>
      </div>

      <PageFootnote>
        직무는 비교 기준일 뿐 사용자를 분류하지 않습니다. 공고 수는 현재 수집된 공고 집합의
        크기이며 채용시장 전체 규모가 아닙니다. 지원하는 직무 목록은 계산 서버가 정하며 화면이
        복제하지 않습니다.
      </PageFootnote>
    </div>
  )
}
