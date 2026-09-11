package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.domain.AnalysisJob;
import java.time.Instant;
import java.util.List;

/**
 * Counts are repositories, not files: each currently accepted job targets one repository.
 *
 * <p>그래서 {@code totalCount}는 1로 고정이고 {@code progressPercent}는 0 또는 100만
 * 나온다. 워커가 중간 진행을 발행하지 않아 그 사이 값을 만들 근거가 없다. 단계별
 * 진행률은 워커 연동이 선행돼야 한다.</p>
 */
public record AnalysisStatusResponse(
        String analysisId, String analysisStatus, String currentStage,
        int completedCount, int totalCount, int progressPercent,
        Instant requestedAt, Instant startedAt, Instant finishedAt,
        Integer pollAfterSeconds, String errorCode,
        List<Stage> stages, List<Repository> repositories) {

    /** 계약이 정의한 다섯 상태. 응답에는 이 값만 나간다. */
    public static final String STATUS_QUEUED = "QUEUED";
    public static final String STATUS_RUNNING = "RUNNING";
    public static final String STATUS_SUCCEEDED = "SUCCEEDED";
    public static final String STATUS_PARTIAL_SUCCEEDED = "PARTIAL_SUCCEEDED";
    public static final String STATUS_FAILED = "FAILED";

    public record Stage(String stage, String status, int processed, int total) {}
    public record Repository(String repositoryId, String branchName, String commitSha,
                             String status, String errorCode) {}

    public static AnalysisStatusResponse from(AnalysisJob job, boolean includeRepositories) {
        String status = normalize(job.getStatus());
        boolean terminal = switch (status) {
            case STATUS_SUCCEEDED, STATUS_PARTIAL_SUCCEEDED, STATUS_FAILED -> true;
            default -> false;
        };
        int processed = terminal ? 1 : 0;
        return new AnalysisStatusResponse(job.getAnalysisId(), status, job.getCurrentStage(),
                processed, 1, processed * 100, job.getRequestedAt(), job.getStartedAt(),
                job.getCompletedAt(), terminal ? null : 5, job.getErrorCode(),
                List.of(new Stage(job.getCurrentStage(), status, processed, 1)),
                includeRepositories ? List.of(new Repository(job.getRepositoryId(),
                        job.getBranchName(), job.getCommitSha(), status, job.getErrorCode())) : List.of());
    }

    /**
     * 저장된 상태를 계약이 정의한 다섯 값 중 하나로 접는다.
     *
     * <p>엔티티는 상태를 {@code String}으로 들고 있다. Python 워커도 이 컬럼을 쓰기
     * 때문에 enum으로 좁히면 워커가 보낸 미지의 값에서 읽기가 깨진다
     * ({@link AnalysisJob} 주석). 그래서 저장은 열어 두고 <b>응답 경계에서만</b>
     * 닫는다 — 읽기 안전성과 계약 준수를 둘 다 얻는 지점이 여기다.</p>
     *
     * <p>미지의 값을 그대로 통과시키면 안 된다. 이전 구현은 {@code default}로
     * 흘려보내 {@code RATE_LIMITED}·{@code CANCELED}는 물론 오타나 빈 문자열까지
     * 그대로 나갔고, 클라이언트는 분기할 수 없는 값을 받았다.</p>
     *
     * <p>{@code CANCELED}가 실패로 접히는 것은 다섯 값에 취소가 없기 때문이다.
     * 티켓이 실패를 "분석 작업이 정상적으로 완료되지 못한 경우"로 정의하므로 그
     * 안에 든다. 취소 기능이 생기면 상태 집합부터 다시 정해야 한다.</p>
     */
    private static String normalize(String status) {
        if (status == null) {
            return STATUS_FAILED;
        }
        return switch (status) {
            case "QUEUED" -> STATUS_QUEUED;
            case "RUNNING", "COLLECTING", "ANALYZING", "RATE_LIMITED", "CANCEL_REQUESTED"
                    -> STATUS_RUNNING;
            case "SUCCEEDED", "COMPLETED" -> STATUS_SUCCEEDED;
            case "PARTIAL", "PARTIAL_SUCCEEDED" -> STATUS_PARTIAL_SUCCEEDED;
            case "FAILED", "CANCELED", "CANCELLED" -> STATUS_FAILED;
            // 워커가 우리가 모르는 값을 쓰기 시작하면 여기로 온다. 계약 밖 문자열을
            // 내보내는 대신 종료로 접어 화면이 무한 폴링에 갇히지 않게 한다.
            default -> STATUS_FAILED;
        };
    }
}
