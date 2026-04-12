package com.example.waterbusiness.schedule;

import com.example.waterbusiness.config.TurbidityThresholdProperties;
import com.example.waterbusiness.service.TurbidityThresholdAlertService;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * On cron, scans IV for two-point turbidity thresholds and writes {@code alert_event}.
 */
@Component
@RequiredArgsConstructor
public class TurbidityThresholdScheduler {

    private final TurbidityThresholdProperties turbidityThresholdProperties;
    private final TurbidityThresholdAlertService turbidityThresholdAlertService;

    @Scheduled(cron = "${water.turbidity-threshold.cron:0 */15 * * * ?}")
    public void runScheduledTurbidityThresholdScan() {
        if (!turbidityThresholdProperties.isEnabled()) {
            return;
        }
        turbidityThresholdAlertService.scanAndAlert();
    }
}
