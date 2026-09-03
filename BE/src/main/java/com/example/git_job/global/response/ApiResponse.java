package com.example.git_job.global.response;

import com.fasterxml.jackson.annotation.JsonPropertyOrder;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.RequiredArgsConstructor;

/**
 * 모든 REST 성공 응답의 공통 계약. 데이터가 없어도 같은 구조를 유지하고
 * {@code data}만 {@code null}로 내려 클라이언트 파싱 분기를 없앤다.
 * 실패 응답은 이 클래스가 아니라 {@code ErrorResponse}를 사용한다.
 */
@Getter
@RequiredArgsConstructor(access = AccessLevel.PRIVATE)
@JsonPropertyOrder({"message", "data"})
public class ApiResponse<T> {

    private final String message;
    private final T data;

    public static <T> ApiResponse<T> success(String message, T data) {
        return new ApiResponse<>(message, data);
    }

    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>("요청이 성공적으로 처리되었습니다.", data);
    }

    public static ApiResponse<Void> success() {
        return new ApiResponse<>("요청이 성공적으로 처리되었습니다.", null);
    }


}
