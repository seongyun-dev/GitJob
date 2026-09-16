package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static com.example.git_job.compute.support.ComputeTestSupport.reader;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeApi;
import com.example.git_job.compute.client.dto.CRelatedJobs;
import com.example.git_job.compute.controller.dto.WhatIfResponse;
import com.example.git_job.compute.service.UserEvidenceAssembler.Unavailable;
import com.example.git_job.compute.support.ComputeTestSupport;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * What-if 증가 건수와 신규 부합 목록이 한 결과에서 나오는지 고정한다 (S15P21E102-279).
 *
 * <p>인수 조건이 "What-if 증가 건수와 신규 부합 공고 목록이 동일한 결과를 사용할 것"이다.
 * 두 호출로 나누면 그 사이에 새 Snapshot이 생겼을 때 화면의 "+7건"과 아래 목록이
 * 어긋나는데, 사용자에게는 표시 버그로 보인다.</p>
 */
class WhatIfServiceTest {

    private static final long USER_ID = 7L;
    private static final String RECOMMENDATION = "c-3";

    private CComputeApi compute;
    private WhatIfService service;

    @BeforeEach
    void setUp() {
        compute = mock(CComputeApi.class);
        UserTargetStore targets = mock(UserTargetStore.class);
        ComputeSnapshotStore snapshots = mock(ComputeSnapshotStore.class);
        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH)));
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.of(
                new ComputeSnapshot(USER_ID, "a".repeat(64), "c-1", "c-2", RECOMMENDATION,
                        "ev-1", "BACKEND|서울|신입", Instant.EPOCH)));
        service = new WhatIfService(compute,
                reader(targets, snapshots));
    }

    private static CRelatedJobs page(int offset, int itemCount, int totalCount) {
        List<CRelatedJobs.Job> items = java.util.stream.IntStream.range(0, itemCount)
                .mapToObj(index -> new CRelatedJobs.Job("job-" + index, "saramin",
                        "https://example.test/" + index, "회사", "백엔드", "서울", "신입",
                        "2026-09-01T00:00:00Z", "2026-09-26T14:59:59Z"))
                .toList();
        return new CRelatedJobs(RECOMMENDATION, "calc-1", "cohort-1", "WHAT_IF", "kafka",
                totalCount, offset, 20, 12, 12 + totalCount, totalCount, items, List.of());
    }

    @Test
    @DisplayName("증가 건수와 목록이 한 호출에서 나온다")
    void countsAndItemsComeFromOneCall() {
        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyInt(),
                anyInt())).thenReturn(page(0, 7, 7));

        WhatIfResponse response = service.whatIf(USER_ID, "kafka", 1, 20);

        assertThat(response.counts().increasedCount()).isEqualTo(7);
        assertThat(response.items()).hasSize(7);
        assertThat(response.totalCount()).isEqualTo(7);
        // C 를 한 번만 부른다. 숫자와 목록을 따로 부르면 어긋날 수 있다.
        verify(compute).relatedJobs(RECOMMENDATION, USER_ID, "WHAT_IF", "kafka", 0, 20);
    }

    @Test
    @DisplayName("hasNext는 받은 창의 끝과 전체 수로 판단한다")
    void computesHasNextFromWindow() {
        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyInt(),
                anyInt())).thenReturn(page(0, 20, 45));
        assertThat(service.whatIf(USER_ID, "kafka", 1, 20).hasNext()).isTrue();

        when(compute.relatedJobs(anyString(), anyLong(), anyString(), anyString(), anyInt(),
                anyInt())).thenReturn(page(40, 5, 45));
        assertThat(service.whatIf(USER_ID, "kafka", 3, 20).hasNext()).isFalse();
    }

    @Test
    @DisplayName("결과가 없으면 0이 아니라 상태로 알린다")
    void reportsPendingInsteadOfZero() {
        ComputeSnapshotStore snapshots = mock(ComputeSnapshotStore.class);
        UserTargetStore targets = mock(UserTargetStore.class);
        when(targets.find(USER_ID)).thenReturn(Optional.of(
                new Target("BACKEND", List.of(), List.of(), Instant.EPOCH)));
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.empty());
        UserEvidenceAssembler assembler = mock(UserEvidenceAssembler.class);
        when(assembler.assemble(anyLong()))
                .thenReturn(ComputeTestSupport.unavailable(Unavailable.NO_ANALYSIS));
        WhatIfService pending = new WhatIfService(compute,
                ComputeTestSupport.reader(targets, snapshots, assembler,
                        mock(CComputeSyncService.class)));

        WhatIfResponse response = pending.whatIf(USER_ID, "kafka", 1, 20);

        // counts 가 0 이면 화면이 "늘어나는 공고가 없다"고 말한다. 계산한 적이 없다.
        assertThat(response.counts()).isNull();
        assertThat(response.dataStatus()).isEqualTo("NO_DATA");
    }
}
