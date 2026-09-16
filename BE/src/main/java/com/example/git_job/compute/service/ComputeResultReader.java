package com.example.git_job.compute.service;

import com.example.git_job.compute.client.CComputeException;
import com.example.git_job.compute.controller.dto.ComputeState;
import com.example.git_job.compute.service.UserEvidenceAssembler.Assembled;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.ComputeSnapshotStore.ComputeSnapshot;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
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
 * <h2>Snapshot이 없으면 한 번 만들어 본다</h2>
 *
 * <p>분석 완료 시 C 호출이 실패해도 Kafka 메시지는 정상 처리된다. 그 설계는 옳다 --
 * C가 잠깐 느렸다는 이유로 판정된 근거 수백 건을 다시 쓸 이유가 없다. 그러나 그러면
 * 그 사용자의 결과는 <b>다음 분석이나 목표 직무 변경까지 영영 생기지 않는다.</b></p>
 *
 * <p>그래서 조회 시점에 한 번 시도한다. {@code event_id}가 결정론적이라 이미 계산된
 * 것은 C가 저장된 결과를 그대로 주고, 실패하면 이번 조회만 준비 중으로 끝난다.
 * 스케줄러를 두지 않는 이유는 재계산이 필요한 시점이 곧 누군가 그 화면을 여는
 * 시점이기 때문이다 -- 아무도 보지 않는 결과를 미리 만들 이유가 없다.</p>
 */
@Service
public class ComputeResultReader {

    private static final Logger log = LoggerFactory.getLogger(ComputeResultReader.class);

    private final UserTargetStore targets;
    private final ComputeSnapshotStore snapshots;
    private final UserEvidenceAssembler assembler;
    /**
     * 순환 참조를 끊는다.
     *
     * <p>{@code TargetService -> CComputeSyncService -> ...} 와 이 클래스가 같은
     * 동기화를 쓰는데, 생성자로 직접 받으면 빈 그래프가 돈다. 조회 시점에만 필요하므로
     * 지연해서 받는다.</p>
     */
    private final ObjectProvider<CComputeSyncService> sync;

    public ComputeResultReader(UserTargetStore targets, ComputeSnapshotStore snapshots,
                               UserEvidenceAssembler assembler,
                               ObjectProvider<CComputeSyncService> sync) {
        this.targets = targets;
        this.snapshots = snapshots;
        this.assembler = assembler;
        this.sync = sync;
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
        ComputeSnapshot snapshot = snapshots.findLatest(userId, target.targetKey())
                .orElseGet(() -> recompute(userId));
        if (snapshot == null) {
            return new Computed<>(target, null, pendingState(userId), null);
        }

        try {
            return new Computed<>(target, snapshot, ComputeState.ready(), reader.read(snapshot));
        } catch (CComputeException e) {
            return new Computed<>(target, snapshot, translate(e, userId), null);
        }
    }

    /**
     * 저장된 결과가 없을 때 한 번만 계산을 시도한다.
     *
     * <p>C 장애로 분석 완료 훅이 실패했던 사용자를 구하는 유일한 경로다. 멱등
     * {@code event_id} 덕분에 이미 계산된 것은 다시 계산되지 않고 저장된 결과가 온다.</p>
     *
     * <p>실패를 삼키는 이유는 이 호출이 조회의 곁가지이기 때문이다. C가 여전히 내려가
     * 있으면 아래에서 준비 중 상태를 만들고, 화면은 기다리는 UI를 그린다.</p>
     */
    private ComputeSnapshot recompute(long userId) {
        try {
            return sync.getObject().synchronize(userId).orElse(null);
        } catch (RuntimeException unavailable) {
            log.warn("조회 시점 C 재계산 실패: userId={}, reason={}", userId, unavailable.toString());
            return null;
        }
    }

    /**
     * 결과가 없는 이유.
     *
     * <p>기다리면 생기는 상태와 재분석해야 풀리는 상태를 구분한다. 후자를 준비 중으로
     * 두면 화면이 영원히 기다리고, 사용자는 무엇을 해야 하는지 알 수 없다.</p>
     */
    private ComputeState pendingState(long userId) {
        Assembled assembled = assembler.assemble(userId);
        if (assembled.isReady()) {
            // 보낼 Evidence 는 있는데 결과가 없다. 방금 재계산도 실패했으므로 C 쪽이다.
            return ComputeState.preparing("COMPUTING");
        }
        return switch (assembled.unavailable()) {
            case NO_ANALYSIS -> ComputeState.notAnalyzed();
            // 아래 둘은 기다려서 풀리지 않는다. 재분석해야 v3 계약의 Rule Pack 계보가
            // 들어오고, 그래야 C 가 근거를 받아들인다.
            case NO_RULE_PACK_LINEAGE -> ComputeState.failed("REANALYSIS_REQUIRED_NO_RULE_PACK");
            case MIXED_RULE_PACK -> ComputeState.failed("REANALYSIS_REQUIRED_MIXED_RULE_PACK");
        };
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
