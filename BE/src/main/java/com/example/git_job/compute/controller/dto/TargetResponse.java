package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.store.UserTargetStore.Target;
import java.time.Instant;
import java.util.List;

/**
 * 목표 직무 (S15P21E102-279).
 *
 * <p>{@code targetKey}는 서버가 만든 정규화 문자열이다. FE는 이 값을 캐시 키로만 쓰고
 * 해석하지 않는다. FE가 직무·지역·경력에서 직접 키를 만들면 공백이나 순서 차이로 같은
 * 조건에 두 벌의 캐시가 생기고, 화면마다 다른 결과를 보게 된다.</p>
 */
public record TargetResponse(String targetRole, List<String> regions, List<String> careerLevels,
        String targetKey, Instant updatedAt) {

    public static TargetResponse of(Target target) {
        return new TargetResponse(target.targetRole(), target.regions(), target.careerLevels(),
                target.targetKey(), target.updatedAt());
    }
}
