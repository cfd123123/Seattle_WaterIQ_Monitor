package com.example.waterbusiness.dto;

import java.util.List;

/**
 * Return value of {@link com.example.waterbusiness.service.AutoForecastBatchService#executeBatch()};
 * scheduler may ignore details and rely on persisted {@code last_run_summary}.
 */
public record AutoForecastBatchExecutionResult(String summary, List<AutoForecastBatchItemResult> batchResults) {}
