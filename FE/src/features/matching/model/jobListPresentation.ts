export const JOBS_PER_PAGE = 10

export function formatJobPagePosition(
  page: number,
  totalCount: number | null,
  perPage = JOBS_PER_PAGE,
): string {
  if (totalCount === null) {
    return `${page}쪽`
  }
  const totalPages = Math.max(1, Math.ceil(totalCount / perPage))
  return `${page} / ${totalPages}`
}
