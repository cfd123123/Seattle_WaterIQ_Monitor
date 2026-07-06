package com.example.waterbusiness.schedule;

import com.example.waterbusiness.config.TurbidityStateProperties;
import com.example.waterbusiness.service.TurbidityStateAlertService;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Periodic four-state turbidity scan via Python {@code POST /turbidity/state/snapshot}.
 */
@Component
@RequiredArgsConstructor
public class TurbidityStateScheduler {

    private final TurbidityStateProperties turbidityStateProperties;
    private final TurbidityStateAlertService turbidityStateAlertService;

    @Scheduled(cron = "${water.turbidity-state.cron:0 */30 * * * ?}")
    public void runScheduledTurbidityStateScan() {
        if (!turbidityStateProperties.isEnabled()) {
            return;
        }
        turbidityStateAlertService.scanAndAlert();
    }
}
