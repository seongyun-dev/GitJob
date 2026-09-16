package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
import com.example.git_job.compute.client.dto.CTrend;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.TrendResponse;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 출처별 기술 Trend (S15P21E102-279).
 *
 * <h2>합치지 않는다</h2>
 *
 * <p>세 출처는 세는 대상과 분모가 다르다. 주간 활동 저장소, 월별 commit 관측, 월별 공고
 * 요구는 단위가 서로 달라 하나의 점수로 더할 수 없다. 그래서 출처마다 상태·단위·점 목록을
 * 따로 내려보내고, 화면도 카드를 따로 그린다.</p>
 *
 * <h2>없는 값을 0으로 채우지 않는다</h2>
 *
 * <p>미완료 기간은 점이 없거나 값이 {@code null}이다. 0을 채우면 화면이 "그 달에는 아무
 * 일도 없었다"고 말하는데, 실제로는 아직 집계하지 않은 것이다.</p>
 *
 * <h2>JOB Trend는 아직 조회할 수 없다</h2>
 *
 * <p>C의 {@code trends/resolve}는 GitHub 계열 세 source만 받는다. JOB Trend는
 * {@code trends/completed}로 저장되지만 B가 그 head를 찾을 경로가 없다. 없는 경로를
 * 추측해 부르는 대신 {@code NOT_SUPPORTED}로 내려보내고 계약 §6에 요청으로 남겼다.</p>
 */
@Service
public class TrendService {

    private static final Logger log = LoggerFactory.getLogger(TrendService.class);

    /** Registry의 tech_id 형식. 임의 문자열을 경로로 넘기지 않는다. */
    private static final Pattern TECH_ID = Pattern.compile("[a-z0-9]+(?:-[a-z0-9]+)*");
    private static final Pattern MONTH = Pattern.compile("\\d{4}-(0[1-9]|1[0-2])");
    private static final int MAX_MONTHS = 24;
    private static final int MAX_COMPARE_TECHS = 10;

    private static final String WEEKLY = "GITHUB_WEEKLY";
    private static final String ARCHIVE = "GITHUB_ARCHIVE";
    private static final String JOB = "JOB";

    private final CComputeApi compute;

    public TrendService(CComputeApi compute) {
        this.compute = compute;
    }

    /**
     * 기술 하나의 출처별 추세.
     *
     * <p>출처 하나가 404여도 나머지는 정상 응답한다. 한 출처의 미준비는 요청 실패가
     * 아니며, 전체를 오류로 만들면 이미 있는 값도 보여 주지 못한다.</p>
     */
    public TrendResponse trends(String techId, List<String> months) {
        String tech = validTechId(techId);
        List<String> periods = validMonths(months);

        List<TrendResponse.Source> sources = new ArrayList<>();
        sources.add(source(WEEKLY, "WEEKLY_REPO_ACTIVITY", CTrend.Selector.weekly(tech),
                "주간 활동 저장소 수"));
        if (!periods.isEmpty()) {
            sources.add(source(ARCHIVE, "GH_ARCHIVE_HISTORICAL",
                    CTrend.Selector.historical(tech, periods), "월별 commit 관측 수"));
        }
        sources.add(TrendResponse.Source.empty(JOB, "JOB_MONTHLY_DEMAND",
                ComputeState.notSupported("JOB_TREND_RESOLVE_UNAVAILABLE"),
                "월별 공고 요구 건수"));
        return new TrendResponse(tech, sources);
    }

    /**
     * 기술 여러 개를 한 출처에서 비교한다.
     *
     * <p>출처를 하나만 받는 것이 이 API의 요점이다. 여러 출처를 한 표에 섞으면 분모가 다른
     * 값이 한 축에 들어가 순위가 뜻을 잃는다.</p>
     */
    public TrendResponse.Compare compare(String sourceId, List<String> techIds,
                                         List<String> months) {
        if (techIds == null || techIds.isEmpty() || techIds.size() > MAX_COMPARE_TECHS) {
            throw new CustomException(ErrorCode.TREND_CRITERIA_INVALID);
        }
        List<String> periods = validMonths(months);
        if (JOB.equals(sourceId)) {
            // 조회 경로가 없다. 빈 표를 주는 대신 지원하지 않는다고 말한다.
            throw new CustomException(ErrorCode.TREND_CRITERIA_INVALID);
        }
        boolean archive = ARCHIVE.equals(sourceId);
        if (!archive && !WEEKLY.equals(sourceId)) {
            throw new CustomException(ErrorCode.TREND_CRITERIA_INVALID);
        }
        if (archive && periods.isEmpty()) {
            throw new CustomException(ErrorCode.TREND_CRITERIA_INVALID);
        }

        List<TrendResponse.Row> rows = new ArrayList<>();
        String unit = null;
        for (String techId : techIds) {
            String tech = validTechId(techId);
            TrendResponse.Source source = source(sourceId,
                    archive ? "GH_ARCHIVE_HISTORICAL" : "WEEKLY_REPO_ACTIVITY",
                    archive ? CTrend.Selector.historical(tech, periods)
                            : CTrend.Selector.weekly(tech),
                    archive ? "월별 commit 관측 수" : "주간 활동 저장소 수");
            unit = source.unit();
            rows.add(lastPoint(tech, source));
        }
        return new TrendResponse.Compare(sourceId,
                archive ? "GH_ARCHIVE_HISTORICAL" : "WEEKLY_REPO_ACTIVITY", unit, rows);
    }

    /** 비교 표는 기간 하나만 보여 준다. 가장 마지막 점이 그 출처의 현재 값이다. */
    private TrendResponse.Row lastPoint(String techId, TrendResponse.Source source) {
        List<TrendResponse.Point> points = source.points();
        if (points.isEmpty()) {
            return new TrendResponse.Row(techId, source.dataStatus(), source.statusReason(),
                    null, null, null, null, null);
        }
        TrendResponse.Point point = points.getLast();
        return new TrendResponse.Row(techId, source.dataStatus(), source.statusReason(),
                point.period(), point.value(), point.ratio(), point.absoluteChange(),
                point.relativeChange());
    }

    /**
     * 출처 하나를 읽는다. resolve로 head를 찾고 그 ID로 수치를 가져온다.
     *
     * <p>{@code TREND_NOT_PREPARED}(404)는 오류가 아니다. 그 출처에 아직 완료된 계산이
     * 없다는 뜻이고, 카드 하나가 비는 것으로 끝난다.</p>
     */
    private TrendResponse.Source source(String sourceId, String cSource,
                                        CTrend.Selector selector, String unit) {
        try {
            CTrend.Resolved resolved = compute.resolveTrend(selector);
            if (resolved == null || resolved.snapshotId() == null) {
                return TrendResponse.Source.empty(sourceId, cSource,
                        ComputeState.ofTrend(null), unit);
            }
            CTrend.Snapshot snapshot = compute.trendSnapshot(resolved.snapshotId());
            CTrend.Payload payload = snapshot == null ? null : snapshot.payload();
            if (payload == null) {
                return TrendResponse.Source.empty(sourceId, cSource,
                        ComputeState.ofTrend(null), unit);
            }
            return TrendResponse.Source.of(sourceId, cSource,
                    ComputeState.ofTrend(payload.status()), payload);
        } catch (CComputeException e) {
            return TrendResponse.Source.empty(sourceId, cSource, trendState(e, sourceId), unit);
        }
    }

    /**
     * Trend 실패를 카드 상태로 바꾼다.
     *
     * <p>매칭과 달리 장애도 예외로 올리지 않는다. Trend는 화면 하나가 통째로 이 값에
     * 의존하지 않고 카드 여럿 중 하나이므로, 한 출처의 장애로 나머지 카드까지 못 그리게
     * 만들 이유가 없다.</p>
     */
    private ComputeState trendState(CComputeException e, String sourceId) {
        return switch (e.getStatus()) {
            case NOT_PREPARED, NOT_FOUND -> ComputeState.ofTrend(null);
            case PREPARING -> ComputeState.computing(e.getRetryAfterSec());
            // 지원하지 않는 기술·기간이다. 요청 전체를 400으로 만들면 다른 출처도 못 본다.
            case INVALID_INPUT -> ComputeState.notSupported("TREND_SELECTOR_REJECTED");
            default -> {
                log.warn("Trend 조회 실패: source={}, status={}, code={}",
                        sourceId, e.getStatus(), e.getCode());
                yield ComputeState.failed("TREND_UNAVAILABLE");
            }
        };
    }

    private static String validTechId(String techId) {
        if (techId == null || !TECH_ID.matcher(techId).matches()) {
            throw new CustomException(ErrorCode.TREND_CRITERIA_INVALID);
        }
        return techId;
    }

    /**
     * 월 목록. 형식과 개수만 본다.
     *
     * <p>비어 있으면 Archive 출처를 조회하지 않는다. C가 기간을 요구하는데 우리가 임의로
     * 최근 몇 달을 고르면, 화면에 표시된 기간과 실제 계산 기간이 달라진다.</p>
     */
    private static List<String> validMonths(List<String> months) {
        if (months == null || months.isEmpty()) {
            return List.of();
        }
        if (months.size() > MAX_MONTHS) {
            throw new CustomException(ErrorCode.TREND_CRITERIA_INVALID);
        }
        List<String> sorted = months.stream()
                .filter(month -> month != null && MONTH.matcher(month).matches())
                .distinct()
                .sorted()
                .toList();
        if (sorted.size() != months.size()) {
            throw new CustomException(ErrorCode.TREND_CRITERIA_INVALID);
        }
        return sorted;
    }
}
