package com.example.git_job.compute.service;

import com.example.git_job.compute.controller.dto.TargetRequest;
import com.example.git_job.compute.store.UserTargetStore;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import org.springframework.stereotype.Service;

/**
 * 목표 직무 조회·저장 (S15P21E102-279).
 *
 * <p>저장 직후 C 계산을 scheduler에 요청한다. 직무가 바뀌면 공고 모집단이 통째로 달라져 기존
 * 결과를 쓸 수 없고, 다음 저장소 분석까지 기다리면 사용자는 직무를 바꾼 뒤 아무것도 보지
 * 못한다. 계산 트리거가 둘인 이유가 이것이다 -- 분석 완료와 목표 직무 변경.</p>
 *
 * <p>계산 실패로 저장을 되돌리지 않는다. 목표 직무는 사용자의 선택이고, C가 잠시 느리다는
 * 이유로 그 선택을 버리면 사용자는 같은 값을 다시 고르게 된다. 계산의 일시 실패는 저장된
 * backoff와 시도 상한을 따르며, 조회 API는 그 상태를 읽기만 한다.</p>
 */
@Service
public class TargetService {

    private final UserTargetStore targets;
    private final ComputeRetryScheduler scheduler;

    public TargetService(UserTargetStore targets, ComputeRetryScheduler scheduler) {
        this.targets = targets;
        this.scheduler = scheduler;
    }

    /** 없으면 {@code null}. 목표 직무 미선택은 오류가 아니라 화면이 다뤄야 할 상태다. */
    public Target find(long userId) {
        return targets.find(userId).orElse(null);
    }

    public Target save(long userId, TargetRequest request) {
        Target saved = targets.save(userId, request.targetRole(), request.regions(),
                request.careerLevels(), Instant.now());
        scheduler.requestInitialSync(userId);
        return saved;
    }
}
