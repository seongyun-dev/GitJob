package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.service.UserEvidenceAssembler.Assembled;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeAttempt;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 개인 계산 결과를 읽는 공통 경로 (S15P21E102-279).
 *
 * <p>공개 API 다섯 개가 같은 세 단계를 거친다. 로그인 사용자의 목표 직무를 찾고, 그
 * 직무의 최신 Snapshot을 고르고, C를 부른 뒤 결과나 상태를 돌려준다. 기능마다 이것을
 * 복제하면 한 곳이 예외를 다르게 다루는 순간 그 화면만 500이 된다.</p>
 *
 * <h2>무엇을 오류로 볼 것인가</h2>
 *
 * <p>계산 대기와 미준비는 오류가 아니다. 잠시 뒤 값이 생기는 상태이고, 화면은 기다리는
 * UI를 그려야 한다. 오류로 올리는 것은 둘뿐이다 -- 사용자가 무언가 해야 하는 경우
 * (목표 직무 선택)와 아무것도 할 수 없는 경우(장애).</p>
 *
 * <h2>GET은 계산하지 않는다</h2>
 *
 * <p>분석 완료 시 C 호출이 실패해도 Kafka 메시지는 정상 처리된다. 그 설계는 옳다 --
 * C가 잠깐 느렸다는 이유로 판정된 근거 수백 건을 다시 쓸 이유가 없다. 그러나 그러면
 * 그 사용자의 결과는 <b>다음 분석이나 목표 직무 변경까지 영영 생기지 않는다.</b></p>
 *
 * <p>계산은 분석 완료와 목표 직무 변경 같은 쓰기 event만 시작한다. 조회가 계산을
 * 시작하면 영구 422도 화면 새로고침마다 다시 전송되고, 같은 event identity의 payload가
 * 달라졌을 때 409가 연쇄된다. 결과가 없으면 저장된 시도 상태만 읽어 화면에 돌려준다.</p>
 */
@Service
public class ComputeResultReader {

    private static final Logger log = LoggerFactory.getLogger(ComputeResultReader.class);

    private final UserTargetStore targets;
    private final ComputeSnapshotStore snapshots;
    private final UserEvidenceAssembler assembler;

    public ComputeResultReader(UserTargetStore targets, ComputeSnapshotStore snapshots,
                               UserEvidenceAssembler assembler) {
        this.targets = targets;
        this.snapshots = snapshots;
        this.assembler = assembler;
    }

    /**
     * 목표 직무. 없으면 404이며 화면은 직무 선택을 권한다.
     *
     * <p>빈 결과로 내리지 않는 이유는, 목표 직무가 없으면 <em>무엇에 대한 매칭인지</em>가
     * 정해지지 않아 보여 줄 수 있는 것이 아무것도 없기 때문이다. 계산을 기다리는 상태와
     * 다르다.</p>
     */
    public Target requireTarget(long userId) {
        return targets.find(userId)
                .orElseThrow(() -> new CustomException(ErrorCode.TARGET_ROLE_NOT_SELECTED));
    }

    /**
     * C를 부르고 결과 또는 상태를 돌려준다.
     *
     * @param reader Snapshot 하나를 받아 C를 호출하는 부분. 여기서 던진
     *               {@link CComputeException}만 상태로 번역된다.
     */
    public <T> Computed<T> read(long userId, Reader<T> reader) {
        Target target = requireTarget(userId);
        ComputeSnapshot snapshot = snapshots.findLatest(userId, target.targetKey()).orElse(null);
        if (snapshot == null) {
            return new Computed<>(target, null, pendingState(userId, target), null);
        }

        try {
            return new Computed<>(target, snapshot, ComputeState.ready(), reader.read(snapshot));
        } catch (CComputeException e) {
            return new Computed<>(target, snapshot, translate(e, userId), null);
        }
    }

    /**
     * 결과가 없는 이유.
     *
     * <p>기다리면 생기는 상태와 재분석해야 풀리는 상태를 구분한다. 후자를 준비 중으로
     * 두면 화면이 영원히 기다리고, 사용자는 무엇을 해야 하는지 알 수 없다.</p>
     */
    private ComputeState pendingState(long userId, Target target) {
        Assembled assembled = assembler.assemble(userId);
        if (assembled.isReady()) {
            Optional<ComputeAttempt> attempt = snapshots.findAttempt(userId, target.targetKey(),
                    assembled.evidenceVersion());
            if (attempt.isPresent()) {
                ComputeAttempt state = attempt.get();
                if (state.failed()) {
                    return ComputeState.failed(state.reason() == null
                            ? "COMPUTE_FAILED" : state.reason());
                }
                int retryAfter = retryAfterSeconds(state.nextRetryAt(), Instant.now());
                return "RETRYING".equals(state.status())
                        ? ComputeState.retrying(retryAfter)
                        : ComputeState.computing(retryAfter);
            }
            return ComputeState.preparing("COMPUTE_PENDING");
        }
        return switch (assembled.unavailable()) {
            case NO_ANALYSIS -> ComputeState.notAnalyzed();
            // 아래 둘은 기다려서 풀리지 않는다. 재분석해야 v3 계약의 Rule Pack 계보가
            // 들어오고, 그래야 C 가 근거를 받아들인다.
            case NO_RULE_PACK_LINEAGE -> ComputeState.failed("REANALYSIS_REQUIRED_NO_RULE_PACK");
            case MIXED_RULE_PACK -> ComputeState.failed("REANALYSIS_REQUIRED_MIXED_RULE_PACK");
        };
    }

    private static int retryAfterSeconds(Instant nextRetryAt, Instant now) {
        if (nextRetryAt == null || !nextRetryAt.isAfter(now)) {
            return 0;
        }
        long millis = Duration.between(now, nextRetryAt).toMillis();
        return (int) Math.min(Integer.MAX_VALUE, (millis + 999) / 1000);
    }

    /**
     * C 예외를 화면 상태로 바꾸거나, 상태로 표현할 수 없는 것은 오류로 올린다.
     *
     * <p>표는 {@code docs/be/c-compute-public-api.md} §2-E다.</p>
     */
    ComputeState translate(CComputeException e, long userId) {
        return switch (e.getStatus()) {
            // 잠시 뒤 값이 생긴다. 화면은 기다린다.
            case PREPARING -> ComputeState.computing(e.getRetryAfterSec());
            case NOT_PREPARED -> ComputeState.preparing("COHORT_NOT_PREPARED");
            case MATCHING_NOT_PREPARED -> ComputeState.preparing("MATCHING_NOT_PREPARED");
            case TIMEOUT -> ComputeState.retrying(e.getRetryAfterSec());
            // 예산을 넘겨 게시되지 못했다. 재시도로 낫지 않으므로 기다리게 하지 않는다.
            case TOO_LARGE -> ComputeState.failed("RESULT_TOO_LARGE");
            // 우리가 저장한 Snapshot ID 인데 C 가 모른다. 사용자 잘못이 아니므로 404 로
            // 내리되, 남의 결과를 감추는 C 의 규약과 같은 코드를 쓴다.
            case NOT_FOUND -> throw new CustomException(ErrorCode.MATCHING_RESULT_NOT_FOUND);
            case INVALID_INPUT -> throw new CustomException(ErrorCode.MATCHING_CRITERIA_INVALID);
            // 아래 둘은 B 버그이거나 C 저장 손상이다. 재시도를 권하면 안 된다.
            case SCOPE_MISMATCH, INTEGRITY_FAILED -> {
                log.error("C 결과 무결성 오류: userId={}, code={}, message={}",
                        userId, e.getCode(), e.getMessage());
                throw new CustomException(ErrorCode.INTERNAL_SERVER_ERROR);
            }
            case CONFLICT, COMPUTE_FAILED, UNAVAILABLE -> {
                log.warn("C 조회 실패: userId={}, status={}, code={}",
                        userId, e.getStatus(), e.getCode());
                throw new CustomException(ErrorCode.COMPUTE_UNAVAILABLE);
            }
        };
    }

    /**
     * 읽기 결과.
     *
     * @param value {@code null}이면 아직 값이 없다는 뜻이고 {@code state}가 이유를 말한다.
     */
    public record Computed<T>(Target target, ComputeSnapshot snapshot, ComputeState state,
            T value) {

        public boolean hasValue() {
            return value != null;
        }
    }

    @FunctionalInterface
    public interface Reader<T> {
        T read(ComputeSnapshot snapshot);
    }

    /** 조회 시점 재계산을 끈 읽기. 테스트와 동기화 자체를 부르는 경로가 쓴다. */
    public Optional<ComputeSnapshot> latest(long userId, Target target) {
        return snapshots.findLatest(userId, target.targetKey());
    }
}
