package com.example.git_job.analysis.controller.dto;

import java.util.List;

/**
 * GitHub은 전체 개수를 주지 않으므로 총 페이지 수를 만들어 낼 수 없다.
 * 받은 항목이 페이지 크기와 같은지로 다음 페이지 존재만 알린다.
 */
public record PageResponse<T>(List<T> items, int page, int perPage, boolean hasNext) {

    public static <T> PageResponse<T> of(List<T> items, int page, int perPage) {
        return new PageResponse<>(items, page, perPage, items.size() == perPage);
    }
}
