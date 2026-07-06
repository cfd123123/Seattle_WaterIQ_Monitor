package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.SiteParamAnomalyIvRequest;
import com.example.waterbusiness.dto.SiteParamAnomalyIvResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.entity.UsgsSiteParamRun;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.example.waterbusiness.repository.UsgsSiteParamRunRepository;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class SiteParamAnomalyService {

    private static final String ALERT_TYPE = "ANOMALY_ALERT";

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final MonitorStationRepository monitorStationRepository;
    private final AlertEventRepository alertEventRepository;
    private final UsgsSiteParamRunRepository usgsSiteParamRunRepository;

    @Retry(name = "waterAiForecastRetry")
    public SiteParamAnomalyIvResponse detectAndAlert(SiteParamAnomalyIvRequest request) {
        SiteParamAnomalyIvRequest pyBody = SiteParamAnomalyIvRequest.builder()
                .siteNo(request.getSiteNo() != null ? request.getSiteNo().trim() : "")
                .parameterCd(request.getParameterCd() != null ? request.getParameterCd().trim() : "")
                .ivCsvPath(blankToNull(request.getIvCsvPath()))
                .build();
        String siteNo = pyBody.getSiteNo();
        String param = pyBody.getParameterCd();

        SiteParamAnomalyIvResponse out = waterAiMaintenanceClient.anomalySiteParamFromIv(pyBody);
        out.setAlertCreated(false);
        out.setAlertReason(null);
        if (out.getAnomalyAvailable() == null || !out.getAnomalyAvailable()) {
            out.setAlertReason(out.getReason() != null ? out.getReason() : "unavailable");
            return out;
        }
        MonitorStation station = monitorStationRepository.findByExternalId(siteNo).orElse(null);
        if (out.getIsAnomaly() == null || !out.getIsAnomaly()) {
            out.setAlertReason("not_anomaly");
            persistSiteParamRun(station, param, out);
            return out;
        }
        if (station == null) {
            out.setAlertReason("station_not_registered");
            return out;
        }
        String ruleCode = "SITE_PARAM_IF_" + param;
        LocalDateTime dedupFrom = LocalDateTime.now().minusHours(6);
        boolean exists = alertEventRepository.existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
                station.getId(), ALERT_TYPE, ruleCode, List.of("NEW", "ACK"), dedupFrom
        );
        if (exists) {
            out.setAlertReason("duplicate_suppressed");
            persistSiteParamRun(station, param, out);
            return out;
        }
        String title = "00060".equals(param) ? "USGS 流量异常" : "USGS 浊度异常";
        AlertEvent e = new AlertEvent();
        e.setStationId(station.getId());
        e.setAlertType(ALERT_TYPE);
        e.setSeverity("MEDIUM");
        e.setStatus("NEW");
        e.setPollutionLevel("ANOMALY");
        e.setTitle(title);
        e.setDetail(
                "site_no=" + siteNo
                        + ", parameter_cd=" + param
                        + ", score=" + out.getAnomalyScore()
                        + ", threshold=" + out.getThreshold()
                        + ", samples_used=" + out.getSamplesUsed()
                        + ", model=" + out.getModelVersion()
        );
        e.setRuleCode(ruleCode);
        e.setCreatedAt(LocalDateTime.now());
        alertEventRepository.save(e);
        out.setAlertCreated(true);
        out.setAlertReason("alert_created");
        persistSiteParamRun(station, param, out);
        return out;
    }

    /**
     * Persists one row whenever a check is usable and the station is registered, for trend detection counts (includes non-anomaly and dedupe skips).
     */
    private void persistSiteParamRun(MonitorStation station, String parameterCd, SiteParamAnomalyIvResponse out) {
        if (station == null) {
            return;
        }
        UsgsSiteParamRun r = new UsgsSiteParamRun();
        r.setStationId(station.getId());
        r.setParameterCd(parameterCd);
        r.setSampleTimestamp(out.getSampleTimestamp());
        r.setIsAnomaly(Boolean.TRUE.equals(out.getIsAnomaly()));
        r.setAlertCreated(Boolean.TRUE.equals(out.getAlertCreated()));
        r.setCreatedAt(LocalDateTime.now());
        usgsSiteParamRunRepository.save(r);
    }

    private static String blankToNull(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        return s;
    }
}
