package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.AutoForecastSettingsResponse;
import com.example.waterbusiness.entity.AutoForecastSettings;
import com.example.waterbusiness.repository.AutoForecastSettingsRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class AutoForecastSettingsService {

    private final AutoForecastSettingsRepository autoForecastSettingsRepository;

    @Value("${water.auto-forecast.cron:0 0 2 * * ?}")
    private String scheduleCron;

    @Transactional
    public AutoForecastSettings getOrCreate() {
        return autoForecastSettingsRepository
                .findById(AutoForecastSettings.SINGLETON_ID)
                .orElseGet(
                        () -> {
                            AutoForecastSettings s = new AutoForecastSettings();
                            s.setId(AutoForecastSettings.SINGLETON_ID);
                            s.setEnabled(false);
                            return autoForecastSettingsRepository.save(s);
                        }
                );
    }

    public AutoForecastSettingsResponse getResponse() {
        AutoForecastSettings s = getOrCreate();
        return AutoForecastSettingsResponse.builder()
                .enabled(s.isEnabled())
                .lastRunAt(s.getLastRunAt())
                .lastRunSummary(s.getLastRunSummary())
                .scheduleCron(scheduleCron)
                .build();
    }

    @Transactional
    public AutoForecastSettingsResponse setEnabled(boolean enabled) {
        AutoForecastSettings s = getOrCreate();
        s.setEnabled(enabled);
        autoForecastSettingsRepository.save(s);
        return getResponse();
    }

    public boolean isEnabled() {
        return getOrCreate().isEnabled();
    }

    @Transactional
    public void updateLastRun(LocalDateTime at, String summary) {
        AutoForecastSettings s = getOrCreate();
        s.setLastRunAt(at);
        s.setLastRunSummary(summary);
        autoForecastSettingsRepository.save(s);
    }
}
