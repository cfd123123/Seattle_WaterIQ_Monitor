package com.example.waterbusiness.dto;

import lombok.Builder;

@Builder
public record ForecastBatchTaskMessage(
        String taskId,
        String taskType
) {
}
