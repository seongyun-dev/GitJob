package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
import com.example.git_job.compute.client.dto.CTrendRanking;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.controller.dto.TrendRankingResponse;
import com.example.git_job.global.exceptions.CustomException;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * 순위는 모집단 전체에서 나온다 (S15P21E102-346).
 *
 * <p>화면이 기술을 고르면 답이 "고른 것들 중의 순위"가 된다. 그래서 이 경로는 기술
 * 목록을 보내지 않고, 주간·월별이 같은 출처를 쓰되 granularity 만 갈린다.</p>
 */
class TrendRankingServiceTest {

    private static final String ARCHIVE = "GITHUB_ARCHIVE";
    private static final String WEEKLY = "GITHUB_WEEKLY";

    private CComputeApi compute;
    private TrendService service;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        service = new TrendService(compute);
        when(compute.trendRankings(anyString(), anyString(), anyString(), anyInt()))
                .thenReturn(ranking(
                        new CTrendRanking.Technology("html", "HTML", 1, 447L,
                                "INSUFFICIENT_DATA"),
                        new CTrendRanking.Technology("rust", "Rust", 2, 9L, "READY")));
    }

    private static CTrendRanking ranking(CTrendRanking.Technology... items) {
        return new CTrendRanking("GITHUB_GH_ARCHIVE", "MONTH", "2026-08",
                List.of("2026-07", "2026-08"), "REPOSITORIES", 695L,
                "registry-20260911.4", 44, List.of(items));
    }

    private String[] sentRequest() {
        ArgumentCaptor<String> source = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> granularity = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> period = ArgumentCaptor.forClass(String.class);
        verify(compute).trendRankings(source.capture(), granularity.capture(),
                period.capture(), anyInt());
        return new String[] {source.getValue(), granularity.getValue(), period.getValue()};
    }

    @Test
    @DisplayName("월별은 GH_ARCHIVE 의 MONTH 를 읽는다")
    void monthlyReadsArchiveMonth() {
        service.rankings(ARCHIVE, "MONTH", "2026-08", 10);

        assertThat(sentRequest()).containsExactly("GITHUB_GH_ARCHIVE", "MONTH", "2026-08");
    }

    @Test
    @DisplayName("주간도 같은 출처를 쓰고 granularity 만 갈린다")
    void weeklyReadsTheSameSourceWithWeekGranularity() {
        service.rankings(WEEKLY, "WEEK", "2026-09-07", 10);

        assertThat(sentRequest()).containsExactly("GITHUB_GH_ARCHIVE", "WEEK", "2026-09-07");
    }

    @Test
    @DisplayName("서버가 준 순위와 값을 그대로 옮긴다")
    void passesThroughRankAndValue() {
        TrendRankingResponse response = service.rankings(ARCHIVE, "MONTH", "2026-08", 10);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.READY);
        assertThat(response.technologies())
                .extracting(TrendRankingResponse.Technology::techId,
                        TrendRankingResponse.Technology::rank,
                        TrendRankingResponse.Technology::value)
                .containsExactly(
                        org.assertj.core.groups.Tuple.tuple("html", 1, 447L),
                        org.assertj.core.groups.Tuple.tuple("rust", 2, 9L));
        assertThat(response.technologyPopulation()).isEqualTo(44);
        // 순위 값의 단위와 분모를 함께 옮긴다. 분모가 없으면 화면이 447을 절대값으로
        // 읽고, 모집단이 다른 주차끼리 비교하게 된다.
        assertThat(response.unit()).isEqualTo("REPOSITORIES");
        assertThat(response.sampleRepoCount()).isEqualTo(695L);
        // 화면이 물은 출처 이름을 그대로 돌려준다. C 출처 이름을 되돌리면 주간·월별이
        // 둘 다 GITHUB_GH_ARCHIVE 로 보여 구별되지 않는다.
        assertThat(response.sourceId()).isEqualTo(ARCHIVE);
    }

    @Test
    @DisplayName("게시된 기간 목록을 그대로 옮긴다 — 카드가 기간을 옮길 수 있게")
    void carriesTheAvailablePeriods() {
        TrendRankingResponse response = service.rankings(ARCHIVE, "MONTH", "2026-08", 10);

        assertThat(response.availablePeriods()).containsExactly("2026-07", "2026-08");
    }

    @Test
    @DisplayName("표본이 얇아도 순위에 남고 상태는 올려 적지 않는다")
    void keepsTheThinSampleVerdict() {
        TrendRankingResponse response = service.rankings(ARCHIVE, "MONTH", "2026-08", 10);

        assertThat(response.technologies().get(0).dataStatus()).isEqualTo("INSUFFICIENT_DATA");
    }

    @Test
    @DisplayName("결과가 비면 오류가 아니라 준비 중이다")
    void emptyRankingIsPreparing() {
        when(compute.trendRankings(anyString(), anyString(), anyString(), anyInt()))
                .thenReturn(ranking());

        TrendRankingResponse response = service.rankings(ARCHIVE, "MONTH", "2020-01", 10);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.PREPARING);
        assertThat(response.technologies()).isEmpty();
        // 값이 없어도 기간 목록은 남는다. 버리면 아직 집계되지 않은 기간으로 옮겨 간
        // 화면이 되돌아올 길을 잃는다.
        assertThat(response.availablePeriods()).containsExactly("2026-07", "2026-08");
        // 기간은 C 가 실제로 읽은 값을 남긴다. 요청이 기간을 비워 보낼 수 있어서,
        // 요청값을 그대로 되돌리면 화면이 어느 기간을 본 것인지 알 수 없다.
        assertThat(response.period()).isEqualTo("2026-08");
    }

    @Test
    @DisplayName("C 가 미준비를 말하면 기다리는 상태로 옮긴다")
    void notPreparedBecomesPreparing() {
        when(compute.trendRankings(anyString(), anyString(), anyString(), anyInt()))
                .thenThrow(new CComputeException(CComputeStatus.NOT_PREPARED, "TREND_NOT_PREPARED", (Integer) null, "not prepared"));

        TrendRankingResponse response = service.rankings(ARCHIVE, "MONTH", "2026-08", 10);

        assertThat(response.dataStatus()).isEqualTo(ComputeState.PREPARING);
        // C 가 답하지 못했으면 기간 목록을 지어내지 않는다.
        assertThat(response.availablePeriods()).isEmpty();
    }

    @Test
    @DisplayName("형식이 어긋난 기간은 C 를 부르지 않고 막는다")
    void rejectsMalformedPeriodBeforeCallingCompute() {
        assertThatThrownBy(() -> service.rankings(ARCHIVE, "MONTH", "2026-8", 10))
                .isInstanceOf(CustomException.class);
        assertThatThrownBy(() -> service.rankings(WEEKLY, "WEEK", "2026-09", 10))
                .isInstanceOf(CustomException.class);

        verify(compute, never()).trendRankings(anyString(), anyString(), anyString(), anyInt());
    }

    @Test
    @DisplayName("JOB 출처와 알 수 없는 granularity 는 거절한다")
    void rejectsUnsupportedScope() {
        assertThatThrownBy(() -> service.rankings("JOB", "MONTH", "2026-08", 10))
                .isInstanceOf(CustomException.class);
        assertThatThrownBy(() -> service.rankings(ARCHIVE, "DAY", "2026-08", 10))
                .isInstanceOf(CustomException.class);

        verify(compute, never()).trendRankings(anyString(), anyString(), anyString(), anyInt());
    }

    @Test
    @DisplayName("기간을 비우면 C 가 최신 기간을 고르게 둔다")
    void anAbsentPeriodIsLeftToCompute() {
        service.rankings(WEEKLY, "WEEK", null, 10);

        verify(compute).trendRankings("GITHUB_GH_ARCHIVE", "WEEK", null, 10);
    }
}
