package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.AsyncTaskStatusResponse;
import com.example.waterbusiness.dto.UsgsIvRefreshRequest;
import com.example.waterbusiness.service.AsyncTaskService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/tasks")
@RequiredArgsConstructor
@Tag(name = "Async tasks", description = "Submit and query long-running background tasks")
public class AsyncTaskController {

    private final AsyncTaskService asyncTaskService;

    @PostMapping("/iv-refresh")
    @Operation(summary = "Submit async IV refresh task")
    public ApiResponse<AsyncTaskStatusResponse> submitIvRefresh(
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @Valid @RequestBody(required = false) UsgsIvRefreshRequest request
    ) {
        return ApiResponse.ok(asyncTaskService.submitIvRefresh(request, idempotencyKey));
    }

    @PostMapping("/forecast-batch-run-now")
    @Operation(summary = "Submit async forecast batch task")
    public ApiResponse<AsyncTaskStatusResponse> submitForecastBatchRunNow(
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey
    ) {
        return ApiResponse.ok(asyncTaskService.submitForecastBatchRunNow(idempotencyKey));
    }

    @GetMapping("/{taskId}")
    @Operation(summary = "Get async task status")
    public ApiResponse<AsyncTaskStatusResponse> getTask(@PathVariable String taskId) {
        return ApiResponse.ok(asyncTaskService.getTask(taskId));
    }

    @GetMapping
    @Operation(summary = "List recent async tasks")
    public ApiResponse<List<AsyncTaskStatusResponse>> listTasks(
            @RequestParam(defaultValue = "20") int limit
    ) {
        return ApiResponse.ok(asyncTaskService.listRecent(limit));
    }

    @PutMapping("/{taskId}/cancel")
    @Operation(summary = "Cancel async task (best effort)")
    public ApiResponse<AsyncTaskStatusResponse> cancelTask(@PathVariable String taskId) {
        return ApiResponse.ok(asyncTaskService.cancelTask(taskId));
    }
}
