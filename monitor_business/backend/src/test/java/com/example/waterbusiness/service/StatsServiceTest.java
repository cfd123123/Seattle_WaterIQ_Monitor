package com.example.waterbusiness.service;

import com.example.waterbusiness.config.StatsProperties;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.ModelCallLogRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.example.waterbusiness.repository.UsgsSiteParamRunRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.assertThrows;

@ExtendWith(MockitoExtension.class)
class StatsServiceTest {

    @Mock
    private UsgsSiteParamRunRepository usgsSiteParamRunRepository;

    @Mock
    private AlertEventRepository alertEventRepository;

    @Mock
    private ModelCallLogRepository modelCallLogRepository;

    @Mock
    private MonitorStationRepository monitorStationRepository;

    private StatsService statsService;

    @BeforeEach
    void setUp() {
        StatsProperties statsProperties = new StatsProperties();
        statsProperties.setMaxRangeDays(365);
        statsService = new StatsService(
                usgsSiteParamRunRepository,
                alertEventRepository,
                modelCallLogRepository,
                monitorStationRepository,
                statsProperties
        );
    }

    @Test
    void distribution_shouldThrowWhenOnlyFromProvided() {
        assertThrows(
                ResponseStatusException.class,
                () -> statsService.distribution(LocalDate.of(2026, 3, 1), null)
        );
    }

    @Test
    void trend_shouldThrowWhenRangeTooLarge() {
        assertThrows(
                ResponseStatusException.class,
                () -> statsService.trend(LocalDate.of(2024, 1, 1), LocalDate.of(2026, 3, 30), "day", null)
        );
    }
}
