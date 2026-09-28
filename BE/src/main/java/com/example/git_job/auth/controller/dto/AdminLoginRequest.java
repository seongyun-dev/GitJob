package com.example.git_job.auth.controller.dto;

/**
 * 관리자 ID/PW 로그인 요청. 값 검증·비교는 서비스에서 상수시간으로 한다.
 * 비밀번호가 로그·예외 메시지에 새지 않도록 이 레코드는 toString을 커스터마이즈하지 않는다
 * (record 기본 toString이 필드를 노출하므로, 이 객체는 로깅하지 않는다).
 */
public record AdminLoginRequest(String id, String password) {
}
