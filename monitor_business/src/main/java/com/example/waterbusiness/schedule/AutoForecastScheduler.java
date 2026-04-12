package com.example.waterbusiness.schedule;

import com.example.waterbusiness.service.AutoForecastBatchService;
import com.example.waterbusiness.service.AutoForecastSettingsService;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * When enabled, runs the same batch forecast as run-batch-now on {@code water.auto-forecast.cron}.
 */
@Component
@RequiredArgsConstructor
public class AutoForecastScheduler {

    private final AutoForecastSettingsService autoForecastSettingsService;
    private final AutoForecastBatchService autoForecastBatchService;

    @Scheduled(cron = "${water.auto-forecast.cron:0 0 2 * * ?}")
    public void runScheduledForecastBatch() {
        if (!autoForecastSettingsService.isEnabled()) {
            return;
        }
        autoForecastBatchService.executeBatch();
    }
}
