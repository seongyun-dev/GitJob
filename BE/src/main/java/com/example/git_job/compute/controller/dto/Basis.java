package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.store.UserTargetStore.Target;
import java.util.List;
import java.util.Map;

/**
 * 이 수치가 무엇을 기준으로 나온 것인지 (S15P21E102-279).
 *
 * <p>화면이 "서울 · 신입 백엔드 공고 87건 기준"이라고 말할 수 있어야 한다. 기준을 숨기면
 * 사용자가 숫자를 절대값으로 읽고, 필터를 바꿔 숫자가 달라지는 것을 오류로 여긴다.</p>
 *
 * <p>{@code asOf}와 정규화된 직무 이름은 우리가 보낸 selector가 아니라 C가 정규화한
 * {@code criteria}에서 온다. C가 "언제까지의 공고인지"를 정하기 때문이다.</p>
 *
 * <p>Snapshot ID는 넣지 않는다. 내려보내면 FE가 그것을 다시 보내는 경로가 생기고, 그
 * 경로는 곧 남의 Snapshot ID를 넣어 보는 시도가 된다.</p>
 */
public record Basis(
        String targetRole,
        List<String> regions,
        List<String> careerLevels,
        String asOf,
        Integer jobCount
) {

    public static Basis of(Target target) {
        return new Basis(target.targetRole(), target.regions(), target.careerLevels(), null, null);
    }

    /** C가 정규화한 조건과 실제 분모를 얹는다. */
    public static Basis of(Target target, CSnapshot.Demand demand) {
        if (demand == null) {
            return of(target);
        }
        return new Basis(
                criterion(demand.criteria(), "target_role", target.targetRole()),
                target.regions(),
                target.careerLevels(),
                criterion(demand.criteria(), "as_of", null),
                demand.denominator());
    }

    private static String criterion(Map<String, Object> criteria, String key, String fallback) {
        if (criteria == null) {
            return fallback;
        }
        Object value = criteria.get(key);
        return value == null ? fallback : String.valueOf(value);
    }
}
