package com.example.git_job.analysis.service;

import com.example.git_job.analysis.controller.dto.AnalysisHistoryResponse;
import com.example.git_job.analysis.controller.dto.AnalysisStatusResponse;
import com.example.git_job.analysis.store.AnalysisHistoryStore;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 마이페이지 분석 이력 (B-FN-009, 화면 14).
 *
 * <p>대상은 항상 세션의 주인이다. 사용자 ID를 밖에서 받지 않으므로 남의 이력을
 * 요청할 방법이 없다.</p>
 */
@Service
@RequiredArgsConstructor
public class AnalysisHistoryService {

    /** 한 쪽의 최대 크기. 화면이 보낸 값이 그대로 LIMIT 이 되면 한 번의 요청이 표 전체를 끈다. */
    private static final int MAX_SIZE = 50;

    private final AnalysisHistoryStore history;

    @Transactional(readOnly = true)
    public AnalysisHistoryResponse list(long userId, int page, int size) {
        int safePage = Math.max(page, 0);
        int safeSize = Math.clamp(size, 1, MAX_SIZE);

        List<AnalysisHistoryResponse.Item> items =
                history.page(userId, safePage * safeSize, safeSize).stream()
                        .map(AnalysisHistoryService::toItem)
                        .toList();
        return new AnalysisHistoryResponse(items, safePage, safeSize, history.count(userId));
    }

    private static AnalysisHistoryResponse.Item toItem(AnalysisHistoryStore.Row row) {
        /*
          저장된 상태를 그대로 내보내지 않는다. 이 열은 Python 워커도 쓰기 때문에
          COLLECTING·COMPLETED·CANCELLED 같은 값이 들어 있고, 화면 계약이 아는 일곱 값이
          아니다. 진행 조회(B-FN-004)가 쓰는 것과 같은 함수로 접어 두 화면이 같은 분석을
          같은 상태로 보게 한다.
        */
        String status = AnalysisStatusResponse.normalize(row.status());
        return new AnalysisHistoryResponse.Item(
                row.analysisId(),
                row.analyzedAt(),
                repositories(row),
                resultText(status, row),
                status);
    }

    /**
     * 대상 저장소.
     *
     * <p>한 분석은 저장소 하나를 본다. 화면은 목록으로 받으므로 한 칸짜리 목록이다.
     * 이름이 없는 옛 기록은 <b>빈 목록</b>이다 — 저장소 식별자를 이름 자리에 넣으면
     * 화면에 숫자가 저장소 이름처럼 찍힌다.</p>
     */
    private static List<String> repositories(AnalysisHistoryStore.Row row) {
        String name = row.repositoryFullName();
        return name == null || name.isBlank() ? List.of() : List.of(name);
    }

    /**
     * 결과 한 줄.
     *
     * <p>찾은 기술 <b>개수</b>와 그 분석이 닿은 가장 높은 레벨을 적는다. 이름을 늘어놓으면
     * 기술이 열 개 넘는 저장소에서 표 한 칸이 여러 줄이 되고, 어느 이름이 중요한지 화면이
     * 고를 근거도 없다. 무엇을 찾았는지는 Evidence 화면이 답한다.</p>
     *
     * <p>근거 줄 수는 적지 않는다. 근거 줄 수는 답이
     * 아니다 — 규칙 하나가 근거 열 줄을 만들기도 해서 "얼마나 증명했는가"와 비례하지
     * 않는다. 확정 디자인은 {@code L2 이상 6}처럼 기준선 위 개수를 적지만, 기준선을
     * 화면이 정하면 그 아래는 전부 같아 보인다. 레벨을 그대로 보이는 편이 정직하다.</p>
     *
     * <p>찾은 것이 없으면 없다고 적는다. "기술 0"은 숫자를 세긴 했다는 인상을 주지만
     * 실제로는 아무것도 찾지 못했다는 뜻이고, 둘은 화면에서 다르게 읽혀야 한다. 아직
     * 끝나지 않은 분석도 같은 이유로 결과를 적지 않는다.</p>
     */
    private static String resultText(String status, AnalysisHistoryStore.Row row) {
        if (!AnalysisStatusResponse.STATUS_SUCCEEDED.equals(status)
                && !AnalysisStatusResponse.STATUS_PARTIAL_SUCCEEDED.equals(status)) {
            return "결과 없음";
        }
        int found = row.technologies().size();
        if (found == 0) {
            return "확인된 기술 없음";
        }
        return row.maxLevel() == null
                ? "기술 %d".formatted(found)
                : "기술 %d · 최고 %s".formatted(found, row.maxLevel());
    }
}
