package com.example.git_job.compute.support;

import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.client.dto.EvidencePayload;
import com.example.git_job.compute.service.CComputeSyncService;
import com.example.git_job.compute.service.ComputeResultReader;
import com.example.git_job.compute.service.UserEvidenceAssembler;
import com.example.git_job.compute.service.UserEvidenceAssembler.Assembled;
import com.example.git_job.compute.service.UserEvidenceAssembler.Unavailable;
import com.example.git_job.compute.store.ComputeSnapshotStore;
import com.example.git_job.compute.store.UserTargetStore;
import java.util.List;
import java.util.Optional;
import org.springframework.beans.factory.ObjectProvider;

/**
 * 계산 결과 조회 테스트의 공통 배선 (S15P21E102-279 후속).
 *
 * <p>{@code ComputeResultReader}는 Snapshot이 없을 때 조립기에게 "왜 없는지"를 묻고,
 * 필요하면 동기화를 한 번 시도한다. 그 두 협력자를 테스트마다 다시 엮으면 같은 배선이
 * 다섯 곳에 복제되고, 협력자가 하나 늘 때마다 다섯 곳을 고치게 된다.</p>
 */
public final class ComputeTestSupport {

    private ComputeTestSupport() {
    }

    /**
     * Snapshot이 있는 경로만 보는 테스트용.
     *
     * <p>조립기는 "보낼 Evidence가 있다"고 답하고 동기화는 아무것도 만들지 않는다.
     * 그래서 Snapshot이 없으면 계산 대기로 끝난다 -- 재분석이 필요한 상태와 섞이지
     * 않게 하려는 기본값이다.</p>
     */
    public static ComputeResultReader reader(UserTargetStore targets,
                                             ComputeSnapshotStore snapshots) {
        UserEvidenceAssembler assembler = mock(UserEvidenceAssembler.class);
        when(assembler.assemble(anyLong())).thenReturn(ready());
        return reader(targets, snapshots, assembler, mock(CComputeSyncService.class));
    }

    public static ComputeResultReader reader(UserTargetStore targets,
                                             ComputeSnapshotStore snapshots,
                                             UserEvidenceAssembler assembler,
                                             CComputeSyncService sync) {
        when(sync.synchronize(anyLong())).thenReturn(Optional.empty());
        return new ComputeResultReader(targets, snapshots, assembler, provider(sync));
    }

    /** 보낼 Evidence가 있는 조립 결과. 내용은 보지 않으므로 최소한만 채운다. */
    public static Assembled ready() {
        EvidencePayload payload = new EvidencePayload(EvidencePayload.SCHEMA_VERSION, "7",
                "u7-x", "registry-20260911.4", UserEvidenceAssembler.LEVEL_POLICY_VERSION,
                "rule-pack-20260911.4", "COMPLETE", List.of(), List.of(), List.of());
        return new Assembled("f".repeat(64), payload, null);
    }

    public static Assembled unavailable(Unavailable reason) {
        return new Assembled(null, null, reason);
    }

    /** 지연 조회용 최소 구현. 순환 참조를 끊으려고 프로덕션이 쓰는 형태다. */
    private static ObjectProvider<CComputeSyncService> provider(CComputeSyncService sync) {
        return new ObjectProvider<>() {
            @Override
            public CComputeSyncService getObject() {
                return sync;
            }

            @Override
            public CComputeSyncService getObject(Object... args) {
                return sync;
            }

            @Override
            public CComputeSyncService getIfAvailable() {
                return sync;
            }

            @Override
            public CComputeSyncService getIfUnique() {
                return sync;
            }
        };
    }
}
