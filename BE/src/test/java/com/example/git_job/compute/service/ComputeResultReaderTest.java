package com.example.git_job.compute.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static com.example.git_job.compute.support.ComputeTestSupport.reader;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.client.CComputeStatus;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.service.UserEvidenceAssembler.Unavailable;
import com.example.git_job.compute.support.ComputeTestSupport;
import com.example.git_job.compute.service.ComputeResultReader.Computed;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * C 상태를 화면 상태로 바꾸는 규칙을 고정한다 (S15P21E102-279).
 *
 * <p>인수 조건이 "C 장애 시 BE가 무조건 500으로 뭉개지 말고 계산 대기·미준비·일시 장애를
 * 구분할 것"이다. 이 클래스가 그 구분의 유일한 자리이므로, 여기서 한 줄이 틀리면 화면
 * 다섯 개가 같이 틀린다.</p>
 */
class ComputeResultReaderTest {

    private static final long USER_ID = 7L;
    private static final Target TARGET =
            new Target("BACKEND", List.of("서울"), List.of("신입"), Instant.EPOCH);

    private UserTargetStore targets;
    private ComputeSnapshotStore snapshots;
    private UserEvidenceAssembler assembler;
    private CComputeSyncService sync;
    private ComputeResultReader reader;

    @BeforeEach
    void setUp() {
        targets = mock(UserTargetStore.class);
        snapshots = mock(ComputeSnapshotStore.class);
        assembler = mock(UserEvidenceAssembler.class);
        sync = mock(CComputeSyncService.class);
        reader = ComputeTestSupport.reader(targets, snapshots, assembler, sync);

        when(targets.find(USER_ID)).thenReturn(Optional.of(TARGET));
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.of(snapshot()));
        when(assembler.assemble(anyLong())).thenReturn(ComputeTestSupport.ready());
    }

    private static ComputeSnapshot snapshot() {
        return new ComputeSnapshot(USER_ID, "a".repeat(64), "c-1", "c-2", "c-3", "ev-1",
                "BACKEND|서울|신입", Instant.EPOCH);
    }

    @Test
    @DisplayName("목표 직무가 없으면 404다 — 무엇에 대한 매칭인지가 정해지지 않았다")
    void requiresTarget() {
        when(targets.find(USER_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> reader.read(USER_ID, snapshot -> "value"))
                .isInstanceOf(CustomException.class)
                .satisfies(thrown -> assertThat(((CustomException) thrown).getErrorCode())
                        .isEqualTo(ErrorCode.TARGET_ROLE_NOT_SELECTED));
    }

    @Test
    @DisplayName("분석 전과 계산 대기를 구분한다")
    void separatesNotAnalyzedFromComputing() {
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.empty());

        when(assembler.assemble(USER_ID))
                .thenReturn(ComputeTestSupport.unavailable(Unavailable.NO_ANALYSIS));
        Computed<String> notAnalyzed = reader.read(USER_ID, snapshot -> "value");
        assertThat(notAnalyzed.hasValue()).isFalse();
        // 화면이 "분석 시작"을 권해야 하는 상태다.
        assertThat(notAnalyzed.state().dataStatus()).isEqualTo(ComputeState.NO_DATA);
        assertThat(notAnalyzed.state().statusReason()).isEqualTo("INSUFFICIENT_EVIDENCE");

        when(assembler.assemble(USER_ID)).thenReturn(ComputeTestSupport.ready());
        Computed<String> computing = reader.read(USER_ID, snapshot -> "value");
        // 분석은 끝났고 계산만 남았다. 곧 값이 생기므로 기다리는 화면이다.
        assertThat(computing.state().dataStatus()).isEqualTo(ComputeState.PREPARING);
        assertThat(computing.state().statusReason()).isEqualTo("COMPUTE_PENDING");
    }

    @Test
    @DisplayName("재분석해야 풀리는 상태를 계산 대기로 두지 않는다")
    void separatesReanalysisFromWaiting() {
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.empty());

        for (Unavailable reason : List.of(Unavailable.NO_RULE_PACK_LINEAGE,
                Unavailable.MIXED_RULE_PACK)) {
            when(assembler.assemble(USER_ID))
                    .thenReturn(ComputeTestSupport.unavailable(reason));

            // 기다린다고 생기지 않는다. 준비 중으로 두면 화면이 영원히 기다리고
            // 사용자는 무엇을 해야 하는지 알 수 없다.
            assertThat(reader.read(USER_ID, snapshot -> "value").state().dataStatus())
                    .isEqualTo(ComputeState.FAILED);
        }
    }

    @Test
    @DisplayName("Snapshot이 없어도 GET은 계산을 시작하지 않는다")
    void readDoesNotRecomputeWhenSnapshotIsMissing() {
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.empty());

        Computed<String> first = reader.read(USER_ID, snapshot -> "value");
        Computed<String> second = reader.read(USER_ID, snapshot -> "value");

        assertThat(first.state().dataStatus()).isEqualTo(ComputeState.PREPARING);
        assertThat(second.state().dataStatus()).isEqualTo(ComputeState.PREPARING);
        verify(sync, never()).synchronize(USER_ID);
    }

    @Test
    @DisplayName("저장된 422 terminal failure는 새로고침해도 FAILED로 유지한다")
    void exposesStoredTerminalFailure() {
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.empty());
        when(snapshots.findAttempt(anyLong(), anyString(), anyString())).thenReturn(Optional.of(
                new ComputeAttempt(USER_ID, "BACKEND|서울|신입", "f".repeat(64), "FAILED",
                        "COMPUTE_INVALID_INPUT", 1, UUID.randomUUID(), null, Instant.EPOCH)));

        Computed<String> computed = reader.read(USER_ID, snapshot -> "value");

        assertThat(computed.state().dataStatus()).isEqualTo(ComputeState.FAILED);
        assertThat(computed.state().statusReason()).isEqualTo("COMPUTE_INVALID_INPUT");
        verify(sync, never()).synchronize(USER_ID);
    }

    @Test
    @DisplayName("일시 실패 backoff는 RETRYING과 남은 시간을 노출한다")
    void exposesStoredRetryState() {
        when(snapshots.findLatest(anyLong(), anyString())).thenReturn(Optional.empty());
        when(snapshots.findAttempt(anyLong(), anyString(), anyString())).thenReturn(Optional.of(
                new ComputeAttempt(USER_ID, "BACKEND|서울|신입", "f".repeat(64), "RETRYING",
                        "COMPUTE_RETRYING", 1, UUID.randomUUID(),
                        Instant.now().plusSeconds(30), Instant.now())));

        Computed<String> computed = reader.read(USER_ID, snapshot -> "value");

        assertThat(computed.state().dataStatus()).isEqualTo(ComputeState.PREPARING);
        assertThat(computed.state().statusReason()).isEqualTo("COMPUTE_RETRYING");
        assertThat(computed.state().retryAfterSec()).isBetween(1, 30);
    }

    @Test
    @DisplayName("계산 중은 오류가 아니라 200 + PREPARING이고 Retry-After를 전달한다")
    void mapsPreparingToState() {
        Computed<String> computed = reader.read(USER_ID, snapshot -> {
            throw new CComputeException(CComputeStatus.PREPARING, "PREPARING", 2, "computing");
        });

        assertThat(computed.hasValue()).isFalse();
        assertThat(computed.state().dataStatus()).isEqualTo(ComputeState.PREPARING);
        assertThat(computed.state().retryAfterSec()).isEqualTo(2);
    }

    @Test
    @DisplayName("공고 모집단 미준비와 매칭 미준비를 구분해 남긴다")
    void mapsNotPreparedStates() {
        assertThat(stateOf(CComputeStatus.NOT_PREPARED).statusReason())
                .isEqualTo("COHORT_NOT_PREPARED");
        assertThat(stateOf(CComputeStatus.MATCHING_NOT_PREPARED).statusReason())
                .isEqualTo("MATCHING_NOT_PREPARED");
        // 예산 초과는 기다려도 낫지 않는다. 준비 중으로 두면 화면이 영영 기다린다.
        assertThat(stateOf(CComputeStatus.TOO_LARGE).dataStatus()).isEqualTo(ComputeState.FAILED);
    }

    @Test
    @DisplayName("없는 결과는 404, 잘못된 조건은 400이다")
    void mapsClientErrors() {
        assertThatThrownBy(() -> reader.read(USER_ID, snapshot -> {
            throw new CComputeException(CComputeStatus.NOT_FOUND, "SNAPSHOT_NOT_FOUND", null, "x");
        })).isInstanceOf(CustomException.class)
                .satisfies(thrown -> assertThat(((CustomException) thrown).getErrorCode())
                        .isEqualTo(ErrorCode.MATCHING_RESULT_NOT_FOUND));

        assertThatThrownBy(() -> reader.read(USER_ID, snapshot -> {
            throw new CComputeException(CComputeStatus.INVALID_INPUT, "INVALID_INPUT", null, "x");
        })).isInstanceOf(CustomException.class)
                .satisfies(thrown -> assertThat(((CustomException) thrown).getErrorCode())
                        .isEqualTo(ErrorCode.MATCHING_CRITERIA_INVALID));
    }

    @Test
    @DisplayName("일시 장애는 500이 아니라 503이다 — 화면이 재시도를 권할 수 있어야 한다")
    void mapsUnavailableToRetryable() {
        for (CComputeStatus status : List.of(CComputeStatus.UNAVAILABLE,
                CComputeStatus.COMPUTE_FAILED, CComputeStatus.CONFLICT)) {
            assertThatThrownBy(() -> reader.read(USER_ID, snapshot -> {
                throw new CComputeException(status, null, null, "x");
            })).isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(((CustomException) thrown).getErrorCode())
                            .isEqualTo(ErrorCode.COMPUTE_UNAVAILABLE));
        }
    }

    @Test
    @DisplayName("무결성 오류는 재시도를 권하지 않는다 — B 버그이거나 저장 손상이다")
    void mapsIntegrityFailures() {
        for (CComputeStatus status : List.of(CComputeStatus.SCOPE_MISMATCH,
                CComputeStatus.INTEGRITY_FAILED)) {
            assertThatThrownBy(() -> reader.read(USER_ID, snapshot -> {
                throw new CComputeException(status, null, null, "x");
            })).isInstanceOf(CustomException.class)
                    .satisfies(thrown -> assertThat(((CustomException) thrown).getErrorCode())
                            .isEqualTo(ErrorCode.INTERNAL_SERVER_ERROR));
        }
    }

    @Test
    @DisplayName("읽는 Snapshot은 서버가 고른다 — 요청이 ID를 지정하지 않는다")
    void usesServerChosenSnapshot() {
        Computed<String> computed = reader.read(USER_ID,
                snapshot -> snapshot.recommendationSnapshotId());

        assertThat(computed.value()).isEqualTo("c-3");
        assertThat(computed.target()).isEqualTo(TARGET);
    }

    private ComputeState stateOf(CComputeStatus status) {
        return reader.read(USER_ID, snapshot -> {
            throw new CComputeException(status, null, null, "x");
        }).state();
    }

    @Test
    @DisplayName("값이 있으면 상태는 READY다")
    void readyWhenValuePresent() {
        assertThat(reader.read(USER_ID, snapshot -> "value").state().isReady()).isTrue();
    }
}
