import { useState } from 'react'
import { Link } from 'react-router'
import { useJobDemands, useSaveTarget, useTarget } from '@/features/matching/hooks/useMatching'
import {
  CAREER_OPTIONS,
  careerSelectionFromValues,
  careerValues,
  normalizeTargetRole,
  TARGET_REGIONS,
  TARGET_ROLES,
  targetRoleDisplayName,
} from '@/features/matching/model/targetOptions'
import type { CareerSelection, TargetRole } from '@/features/matching/model/targetOptions'
import {
  activeMatchingJobCount,
  formatCollectedAt,
} from '@/features/matching/model/presentation'
import { ApiError } from '@/shared/api/client'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import { ComputeStatePanel } from '@/shared/ui/ComputeStatePanel'
import { DataRegion } from '@/shared/ui/DataRegion'
import { MeterBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

interface Form {
  targetRole: TargetRole
  regions: string[]
  career: CareerSelection
}

function toggleValue(values: readonly string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

export function TargetRolePage() {
  const target = useTarget()
  const save = useSaveTarget()
  const saved = target.data
  const [draft, setDraft] = useState<Form | null>(null)
  const form: Form = draft ?? {
    targetRole: normalizeTargetRole(saved?.targetRole) ?? 'BACKEND',
    regions: saved?.regions.filter((region) => TARGET_REGIONS.some((item) => item === region)) ?? [],
    career: careerSelectionFromValues(saved?.careerLevels ?? []),
  }
  const update = (patch: Partial<Form>) => setDraft({ ...form, ...patch })
  const selectedCareerLevels = careerValues(form.career)

  const preview = useJobDemands({
    targetRole: form.targetRole,
    regions: form.regions,
    careerLevels: selectedCareerLevels,
  })
  const technologies = [...(preview.data?.technologies ?? [])]
    .filter((technology) => technology.requiredCount > 0)
    .sort((left, right) => right.requiredCount - left.requiredCount)
  const topCount = Math.max(0, ...technologies.map((technology) => technology.requiredCount))
  const previewJobCount =
    preview.data === undefined ? null : activeMatchingJobCount(preview.data.basis)

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero title="어떤 직무 공고와 비교할까요?" />
        <Link
          to="/evidence"
          className="shrink-0 rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
        >
          ← 내 기술
        </Link>
      </div>

      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
        <form
          className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
          onSubmit={(event) => {
            event.preventDefault()
            save.mutate({
              targetRole: form.targetRole,
              regions: form.regions,
              careerLevels: selectedCareerLevels,
            })
          }}
        >
          <fieldset>
            <legend className="text-[13px] font-[750] text-brand-ink">직무</legend>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {TARGET_ROLES.map((option) => {
                const selected = form.targetRole === option.value
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => update({ targetRole: option.value })}
                    className={`rounded-[10px] border px-3 py-2.5 text-[13px] font-[700] transition ${
                      selected
                        ? 'border-brand-600 bg-brand-50 text-brand-700'
                        : 'border-brand-line bg-white text-brand-muted hover:border-brand-line-active'
                    }`}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>
          </fieldset>

          <fieldset className="mt-5">
            <legend className="text-[13px] font-[750] text-brand-ink">지역</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                aria-pressed={form.regions.length === 0}
                onClick={() => update({ regions: [] })}
                className={`rounded-full border px-3 py-1.5 text-[12.5px] font-[700] transition ${
                  form.regions.length === 0
                    ? 'border-brand-600 bg-brand-50 text-brand-700'
                    : 'border-brand-line bg-white text-brand-muted hover:border-brand-line-active'
                }`}
              >
                전체
              </button>
              {TARGET_REGIONS.map((region) => {
                const selected = form.regions.includes(region)
                return (
                  <button
                    key={region}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => update({ regions: toggleValue(form.regions, region) })}
                    className={`rounded-full border px-3 py-1.5 text-[12.5px] font-[700] transition ${
                      selected
                        ? 'border-brand-600 bg-brand-50 text-brand-700'
                        : 'border-brand-line bg-white text-brand-muted hover:border-brand-line-active'
                    }`}
                  >
                    {region}
                  </button>
                )
              })}
            </div>
          </fieldset>

          <fieldset className="mt-5">
            <legend className="text-[13px] font-[750] text-brand-ink">경력</legend>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {CAREER_OPTIONS.map((option) => {
                const selected = form.career === option.value
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => update({ career: option.value })}
                    className={`rounded-[10px] border px-3 py-2.5 text-[13px] font-[700] transition ${
                      selected
                        ? 'border-brand-600 bg-brand-50 text-brand-700'
                        : 'border-brand-line bg-white text-brand-muted hover:border-brand-line-active'
                    }`}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>
          </fieldset>

          <button
            type="submit"
            disabled={save.isPending}
            className="mt-6 w-full rounded-[10px] bg-brand-ink px-4 py-3 text-[13.5px] font-[750] text-white disabled:cursor-not-allowed disabled:bg-[#B9C4D6]"
          >
            {save.isPending ? '저장 중…' : '조건 저장'}
          </button>

          {save.isError && (
            <p className="mt-3 text-[12.5px] leading-[1.6] text-tone-danger">
              {save.error instanceof ApiError
                ? save.error.message
                : '목표 조건을 저장하지 못했습니다.'}
            </p>
          )}
          {save.isSuccess && (
            <p className="mt-3 text-[12.5px] font-semibold text-tone-success">저장했습니다.</p>
          )}

          {saved !== null && saved !== undefined && (
            <p className="mt-4 border-t border-brand-line pt-4 text-[12.5px] leading-[1.6] text-brand-muted">
              현재 적용 중:{' '}
              <span className="font-[750] text-brand-ink-soft">
                {[
                  targetRoleDisplayName(saved.targetRole),
                  ...(saved.regions.length === 0 ? ['전체 지역'] : saved.regions),
                  ...(saved.careerLevels.length === 0 ? ['경력 전체'] : saved.careerLevels),
                ].join(' · ')}
              </span>
            </p>
          )}
        </form>

        <DataRegion title={`${targetRoleDisplayName(form.targetRole)} 채용 기술 수요`}>
          <ComputeStatePanel
            isLoading={preview.isLoading}
            error={preview.error}
            state={preview.data}
            loadingLabel="기술 수요를 불러오는 중입니다."
            onRetry={() => void preview.refetch()}
          />

          {preview.data !== undefined &&
            preview.data.dataStatus === 'READY' &&
            (technologies.length === 0 ? (
              <StateCard
                kind="NO_DATA"
                title="이 조건의 기술 수요가 아직 없어요"
                description="다른 지역이나 경력 조건을 선택해 보세요."
              />
            ) : (
              <>
                <p className="text-[12px] text-brand-faint">
                  {previewJobCount === null
                    ? '공고 수 미집계'
                    : `공고 ${previewJobCount.toLocaleString('ko-KR')}건 기준`}
                  {' · '}
                  {formatCollectedAt(preview.data.basis.asOf)}
                </p>
                <ol className="mt-3 grid gap-3">
                  {technologies.map((technology, index) => (
                    <li key={technology.techId} className="flex items-start gap-3">
                      <span className="mt-0.5 text-[11px] font-extrabold tabular-nums text-brand-faint">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <p className="truncate text-[13.5px] font-[750] text-brand-ink">
                            {technologyDisplayName(technology.techId)}
                          </p>
                          <span className="shrink-0 text-[12px] tabular-nums text-brand-muted">
                            {technology.requiredCount}건
                          </span>
                        </div>
                        <div className="mt-1.5">
                          <MeterBar
                            value={technology.requiredCount}
                            total={topCount}
                            tone={index === 0 ? 'accent' : 'muted'}
                            height={5}
                          />
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
              </>
            ))}

          <Link
            to="/jobs"
            className="mt-5 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
          >
            공고 매칭 보기
          </Link>
        </DataRegion>
      </div>
    </div>
  )
}
