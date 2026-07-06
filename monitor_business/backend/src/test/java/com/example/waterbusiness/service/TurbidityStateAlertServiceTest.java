package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.config.TurbidityStateProperties;
import com.example.waterbusiness.dto.TurbidityStateHorizonWarningDto;
import com.example.waterbusiness.dto.TurbidityStateSnapshotResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class TurbidityStateAlertServiceTest {

    private static final String SITE = "12117500";

    @Mock
    private WaterAiMaintenanceClient waterAiMaintenanceClient;

    @Mock
    private MonitorStationRepository monitorStationRepository;

    @Mock
    private AlertEventRepository alertEventRepository;

    @Mock
    private TurbidityStateProperties properties;

    @InjectMocks
    private TurbidityStateAlertService service;

    private MonitorStation station;

    @BeforeEach
    void setUp() {
        station = new MonitorStation();
        station.setId(1L);
        station.setExternalId(SITE);
        station.setStationCode("cedar");
        lenient().when(properties.getMonitoredSiteNos()).thenReturn(List.of(SITE));
        lenient().when(properties.getFeaturesCsvPath()).thenReturn("data/features.csv");
        lenient().when(properties.getThresholdsJsonPath()).thenReturn("");
        lenient().when(properties.getDedupHours()).thenReturn(6);
        lenient().when(properties.isAlertOnTierWatch()).thenReturn(true);
        lenient().when(properties.isAlertOnTierHigh()).thenReturn(true);
        lenient().when(properties.isAlertOnTierCritical()).thenReturn(true);
        lenient().when(properties.isAlertOnStateHigh()).thenReturn(false);
        lenient().when(properties.isAlertOnStateRising()).thenReturn(false);
        lenient().when(properties.isAlertOnRuleHorizon6()).thenReturn(true);
        lenient().when(properties.isAlertOnRuleHorizon12()).thenReturn(true);
    }

    @Test
    void checkAndAlert_createsHighTierAlert() {
        TurbidityStateSnapshotResponse snap = snapshot("HIGH", false, false);
        when(waterAiMaintenanceClient.turbidityStateSnapshot(any())).thenReturn(snap);
        when(monitorStationRepository.findByExternalId(SITE)).thenReturn(Optional.of(station));
        when(alertEventRepository.existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
                any(), any(), eq(TurbidityStateAlertService.RULE_TIER_HIGH), any(), any()
        )).thenReturn(false);

        var out = service.checkAndAlert(SITE, null);

        assertThat(out.isAlertCreated()).isTrue();
        verify(alertEventRepository).save(any(AlertEvent.class));
    }

    @Test
    void checkAndAlert_createsWatchTierAlert() {
        TurbidityStateSnapshotResponse snap = snapshot("WATCH", false, false);
        when(waterAiMaintenanceClient.turbidityStateSnapshot(any())).thenReturn(snap);
        when(monitorStationRepository.findByExternalId(SITE)).thenReturn(Optional.of(station));
        when(alertEventRepository.existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
                any(), any(), eq(TurbidityStateAlertService.RULE_TIER_WATCH), any(), any()
        )).thenReturn(false);

        var out = service.checkAndAlert(SITE, null);

        assertThat(out.isAlertCreated()).isTrue();
        verify(alertEventRepository).save(any(AlertEvent.class));
    }

    @Test
    void checkAndAlert_createsCriticalTierAlert() {
        TurbidityStateSnapshotResponse snap = snapshot("CRITICAL", false, false);
        when(waterAiMaintenanceClient.turbidityStateSnapshot(any())).thenReturn(snap);
        when(monitorStationRepository.findByExternalId(SITE)).thenReturn(Optional.of(station));
        when(alertEventRepository.existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
                any(), any(), eq(TurbidityStateAlertService.RULE_TIER_CRITICAL), any(), any()
        )).thenReturn(false);

        var out = service.checkAndAlert(SITE, null);

        assertThat(out.isAlertCreated()).isTrue();
        verify(alertEventRepository).save(any(AlertEvent.class));
    }

    @Test
    void checkAndAlert_skipsGapTiers() {
        for (String gap : List.of("SENSOR_GAP", "DATA_STALE", "UNKNOWN")) {
            TurbidityStateSnapshotResponse snap = snapshot(gap, false, false);
            snap.setIsAnomaly(false);
            when(waterAiMaintenanceClient.turbidityStateSnapshot(any())).thenReturn(snap);
            when(monitorStationRepository.findByExternalId(SITE)).thenReturn(Optional.of(station));

            var out = service.checkAndAlert(SITE, null);

            assertThat(out.isAlertCreated()).isFalse();
            assertThat(out.getAlertReason()).isEqualTo("no_trigger");
        }
    }

    @Test
    void checkAndAlert_skipsDuplicate() {
        TurbidityStateSnapshotResponse snap = snapshot("HIGH", false, false);
        when(waterAiMaintenanceClient.turbidityStateSnapshot(any())).thenReturn(snap);
        when(monitorStationRepository.findByExternalId(SITE)).thenReturn(Optional.of(station));
        when(alertEventRepository.existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
                any(), any(), any(), any(), any()
        )).thenReturn(true);

        var out = service.checkAndAlert(SITE, null);

        assertThat(out.isAlertCreated()).isFalse();
        assertThat(out.getAlertReason()).isEqualTo("no_trigger");
    }

    private static TurbidityStateSnapshotResponse snapshot(String alertTier, boolean h6, boolean h12) {
        TurbidityStateSnapshotResponse snap = new TurbidityStateSnapshotResponse();
        snap.setSiteNo(SITE);
        snap.setAlertTier(alertTier);
        snap.setState("Normal");
        snap.setTurbidityNtu(3.0);
        snap.setIsAnomaly(!"NORMAL".equals(alertTier));
        TurbidityStateHorizonWarningDto w6 = new TurbidityStateHorizonWarningDto();
        w6.setRuleFires(h6);
        TurbidityStateHorizonWarningDto w12 = new TurbidityStateHorizonWarningDto();
        w12.setRuleFires(h12);
        snap.setWarningHorizons(Map.of("6", w6, "12", w12));
        return snap;
    }
}
