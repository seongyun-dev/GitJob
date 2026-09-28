package com.example.git_job.compute.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.example.git_job.compute.controller.AdminComputeAttemptController.RearmRequest;
import com.example.git_job.compute.service.AdminComputeAttemptService;
import com.example.git_job.global.security.AuthenticatedUser;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

class AdminComputeAttemptControllerTest {

    @Test
    void concurrentRearmConflictReturnsConflictInsteadOfInternalServerError() {
        AdminComputeAttemptService service = mock(AdminComputeAttemptService.class);
        AdminComputeAttemptController controller = new AdminComputeAttemptController(service);
        UUID runToken = UUID.randomUUID();
        RearmRequest request = new RearmRequest(
                7L, "BACKEND|서울|신입", "a".repeat(64), runToken, "canary");
        AuthenticatedUser actor = mock(AuthenticatedUser.class);
        when(actor.userId()).thenReturn("42");
        when(service.rearm(7L, "BACKEND|서울|신입", "a".repeat(64), runToken,
                42L, "canary"))
                .thenThrow(new CannotAcquireLockException("serialization conflict"));

        assertThatThrownBy(() -> controller.rearm(request, actor))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> assertThat(error.getStatusCode()).isEqualTo(HttpStatus.CONFLICT));
    }
}
