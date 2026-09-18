package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.only;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
import com.example.git_job.compute.client.dto.CTrend;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.TrendResponse;
import com.example.git_job.global.exceptions.CustomException;
import java.util.List;
import org.mockito.ArgumentCaptor;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 출처를 섞지 않는다는 규칙을 고정한다 (S15P21E102-279).
 *
 * <p>인수 조건이 "JOB Trend와 GitHub Trend를 하나의 합성 점수로 섞지 않고 출처별로 표시할
 * 것"이다. 여기서 한 번 합치면 화면은 그것을 되돌릴 수 없다 -- 단위가 사라진 숫자에서
 * 원래의 두 값을 복원할 방법이 없다.</p>
 */
class TrendServiceTest {

    private CComputeApi compute;
    private TrendService service;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        service = new TrendService(compute);
        when(compute.resolveTrend(any())).thenReturn(
                new CTrend.Resolved("c-trend", "c-gharchive-trend/v1", "READY",
                        "registry-20260911.4", "algo/v1", "WEEK", List.of(), false));
        when(compute.trendSnapshot(anyString())).thenReturn(snapshot("READY"));
    }

    private static CTrend.Snapshot snapshot(String status) {
        return new CTrend.Snapshot("c-trend", "TREND", new CTrend.Payload(
                "c-gharchive-trend/v1", "GITHUB_GH_ARCHIVE", "kafka", "gh_archive_event_count",
                "EVENTS", "MONTH", status, List.of(),
                List.of(new CTrend.Point("2026-07", "READY", null, null, null, null, null,
                                128, 40, List.of()),
                        new CTrend.Point("2026-08", "PARTIAL", null, null, null, null, null,
                                null, null, List.of("INCOMPLETE_MONTH")))));
    }

    @Test
    @DisplayName("출처를 배열로 나눠 내려보내고 합치지 않는다")
    void keepsSourcesSeparate() {
        TrendResponse response = service.trends("kafka", List.of("2026-07", "2026-08"),
                "BACKEND", List.of("서울"), List.of("신입"));

        assertThat(response.sources()).extracting(TrendResponse.Source::sourceId)
                .containsExactly("GITHUB_WEEKLY", "GITHUB_ARCHIVE", "JOB");
        // 단위를 반드시 표시한다. 없으면 화면이 서로 다른 축의 값을 나란히 비교한다.
        assertThat(response.sources()).allSatisfy(
                source -> assertThat(source.unit()).isNotBlank());
    }

    @Test
    @DisplayName("JOB Trend는 목표 직무와 공고 필터를 그대로 C selector에 보낸다")
    void resolvesJobTrendForTheSelectedRole() {
        TrendResponse.Source job = service.trends("kafka", List.of("2026-07"),
                        "BACKEND", List.of("서울"), List.of("신입")).sources().stream()
                .filter(source -> "JOB".equals(source.sourceId()))
                .findFirst()
                .orElseThrow();

        assertThat(job.dataStatus()).isEqualTo(ComputeState.READY);
        ArgumentCaptor<CTrend.Selector> captor = ArgumentCaptor.forClass(CTrend.Selector.class);
        verify(compute, atLeastOnce()).resolveTrend(captor.capture());
        assertThat(captor.getAllValues()).anySatisfy(selector -> {
            assertThat(selector.source()).isEqualTo("JOB");
            assertThat(selector.targetRole()).isEqualTo("BACKEND");
            assertThat(selector.regions()).containsExactly("서울");
            assertThat(selector.careerLevels()).containsExactly("신입");
        });
    }

    @Test
    @DisplayName("기간을 주지 않으면 Archive 출처를 부르지 않는다")
    void doesNotGuessPeriods() {
        TrendResponse response = service.trends("kafka", List.of(),
                "BACKEND", List.of(), List.of());

        // 서버가 최근 몇 달을 임의로 고르면 화면에 적힌 기간과 실제 계산 기간이 달라진다.
        assertThat(response.sources()).extracting(TrendResponse.Source::sourceId)
                .containsExactly("GITHUB_WEEKLY", "JOB");
        assertThat(response.sources().get(1).statusReason())
                .isEqualTo("JOB_TREND_PERIODS_REQUIRED");
    }

    @Test
    @DisplayName("값이 없는 기간을 0으로 채우지 않는다")
    void doesNotFillMissingPeriodsWithZero() {
        List<TrendResponse.Point> points = service.trends("kafka", List.of(),
                        "BACKEND", List.of(), List.of()).sources()
                .getFirst().points();

        assertThat(points).hasSize(2);
        assertThat(points.getFirst().value()).isEqualTo(128);
        // 미완료 월이다. 0 을 넣으면 "그 달에는 아무 일도 없었다"가 된다.
        assertThat(points.get(1).value()).isNull();
        assertThat(points.get(1).status()).isEqualTo("PARTIAL");
    }

    @Test
    @DisplayName("공개 집계에 관측값이 있으면 품질 제한을 부분 상태로 내려보낸다")
    void exposesObservedTrendWithQualityLimits() {
        when(compute.trendSnapshot(anyString())).thenReturn(snapshot("INSUFFICIENT_DATA"));

        TrendResponse.Source source = service.trends("kafka", List.of(),
                "BACKEND", List.of(), List.of()).sources().getFirst();

        assertThat(source.dataStatus()).isEqualTo(ComputeState.PARTIAL);
        assertThat(source.statusReason()).isEqualTo("PARTIAL_TREND_QUALITY");
        assertThat(source.points().getFirst().value()).isEqualTo(128);
    }

    @Test
    @DisplayName("관측값 자체가 없으면 표본 부족 상태를 유지한다")
    void keepsInsufficientStateWhenTrendHasNoObservedValue() {
        CTrend.Payload payload = new CTrend.Payload(
                "c-gharchive-trend/v1", "GITHUB_GH_ARCHIVE", "kafka",
                "gh_archive_event_count", "EVENTS", "MONTH", "INSUFFICIENT_DATA",
                List.of("MISSING_PERIOD_INPUT"),
                List.of(new CTrend.Point("2026-08", "INSUFFICIENT_DATA", null, null,
                        null, null, null, null, null, List.of("MISSING_PERIOD_INPUT"))));
        when(compute.trendSnapshot(anyString()))
                .thenReturn(new CTrend.Snapshot("c-trend", "TREND", payload));

        TrendResponse.Source source = service.trends("kafka", List.of(),
                "BACKEND", List.of(), List.of()).sources().getFirst();

        assertThat(source.dataStatus()).isEqualTo(ComputeState.INSUFFICIENT_DATA);
        assertThat(source.statusReason()).isEqualTo("INSUFFICIENT_TREND_SAMPLE");
    }

    @Test
    @DisplayName("한 출처가 비어도 나머지는 정상 응답한다")
    void isolatesPerSourceFailure() {
        when(compute.resolveTrend(any())).thenThrow(
                new CComputeException(CComputeStatus.NOT_PREPARED, "TREND_NOT_PREPARED", null, "x"));

        TrendResponse response = service.trends("kafka", List.of(),
                "BACKEND", List.of(), List.of());

        assertThat(response.sources().getFirst().dataStatus()).isEqualTo(ComputeState.NO_DATA);
        assertThat(response.sources()).hasSize(2);
    }

    @Test
    @DisplayName("Trend 장애는 요청 실패가 아니라 카드 상태다")
    void degradesInsteadOfFailing() {
        when(compute.resolveTrend(any())).thenThrow(
                new CComputeException(CComputeStatus.UNAVAILABLE, null, null, "x"));

        // 카드 하나 때문에 화면 전체를 못 그리게 만들 이유가 없다.
        assertThat(service.trends("kafka", List.of(), "BACKEND", List.of(), List.of())
                .sources().getFirst().dataStatus())
                .isEqualTo(ComputeState.FAILED);
    }

    @Test
    @DisplayName("기술 식별자와 기간 형식을 검증한다")
    void validatesSelector() {
        assertThatThrownBy(() -> service.trends("Apache Kafka", List.of(),
                "BACKEND", List.of(), List.of()))
                .isInstanceOf(CustomException.class);
        assertThatThrownBy(() -> service.trends("kafka", List.of("2026-13"),
                "BACKEND", List.of(), List.of()))
                .isInstanceOf(CustomException.class);
    }

    @Test
    @DisplayName("비교는 한 번에 한 출처만 본다")
    void compareUsesOneSource() {
        when(compute.resolveTrends(any())).thenAnswer(invocation -> {
            List<CTrend.Selector> selectors = invocation.getArgument(0);
            return new CTrend.Batch(selectors.stream()
                    .map(selector -> new CTrend.BatchItem(
                            selector.techId(), "READY", null, snapshot("READY")))
                    .toList());
        });
        TrendResponse.Compare compare = service.compare("GITHUB_WEEKLY",
                List.of("kafka", "redis"), List.of(), null, List.of(), List.of());

        assertThat(compare.sourceId()).isEqualTo("GITHUB_WEEKLY");
        assertThat(compare.rows()).hasSize(2);
        // 비교 표는 마지막 기간 하나만 보여 준다.
        assertThat(compare.rows().getFirst().period()).isEqualTo("2026-08");

        // 여러 출처를 한 표에 섞는 요청은 받지 않는다.
        TrendResponse.Compare job = service.compare("JOB", List.of("kafka"),
                List.of("2026-07"), "BACKEND", List.of(), List.of());
        assertThat(job.sourceId()).isEqualTo("JOB");
        assertThatThrownBy(() -> service.compare("JOB", List.of("kafka"),
                List.of("2026-07"), null, List.of(), List.of()))
                .isInstanceOf(CustomException.class);
        assertThatThrownBy(() -> service.compare("GITHUB_ARCHIVE", List.of("kafka"), List.of(),
                null, List.of(), List.of()))
                .isInstanceOf(CustomException.class);
    }

    @Test
    @DisplayName("기술 비교는 기술 수와 무관하게 C 배치 API를 한 번만 호출한다")
    void compareUsesOneBatchCall() {
        when(compute.resolveTrends(any())).thenReturn(new CTrend.Batch(List.of(
                new CTrend.BatchItem("kafka", "READY", null, snapshot("READY")),
                new CTrend.BatchItem("redis", "NOT_PREPARED", "TREND_NOT_PREPARED", null))));

        TrendResponse.Compare response = service.compare("GITHUB_WEEKLY",
                List.of("kafka", "redis"), List.of(), null, List.of(), List.of());

        verify(compute, only()).resolveTrends(any());
        assertThat(response.rows()).hasSize(2);
        assertThat(response.rows().get(1).dataStatus()).isEqualTo(ComputeState.NO_DATA);
    }

    @Test
    @DisplayName("Trend 배치 타임아웃은 비교 화면 전체 오류가 아니라 재시도 상태다")
    void batchTimeoutBecomesRetryingRows() {
        when(compute.resolveTrends(any())).thenThrow(
                new CComputeException(CComputeStatus.TIMEOUT, "C_COMPUTE_TIMEOUT", null, "x"));

        TrendResponse.Compare response = service.compare("GITHUB_WEEKLY",
                List.of("kafka", "redis"), List.of(), null, List.of(), List.of());

        assertThat(response.rows()).allSatisfy(row -> {
            assertThat(row.dataStatus()).isEqualTo(ComputeState.PREPARING);
            assertThat(row.statusReason()).isEqualTo("COMPUTE_RETRYING");
        });
    }
}
