package com.example.waterbusiness.dto;

import com.example.waterbusiness.entity.AsyncTaskStatus;
import com.example.waterbusiness.entity.AsyncTaskType;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class AsyncTaskStatusResponse {
    private String taskId;
    private AsyncTaskType taskType;
    private AsyncTaskStatus status;
    private Integer progressPercent;
    private Integer retryCount;
    private String currentStep;
    private String errorMessage;
    private Object result;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
}
