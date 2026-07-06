package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.SiteParamAnomalyIvRequest;
import com.example.waterbusiness.dto.SiteParamAnomalyIvResponse;
import com.example.waterbusiness.dto.UsgsAnomalyFromIvRequest;
import com.example.waterbusiness.dto.UsgsAnomalyRequest;
import com.example.waterbusiness.dto.UsgsAnomalyResponse;
import com.example.waterbusiness.dto.UsgsIvLatestCoreRequest;
import com.example.waterbusiness.dto.UsgsIvLatestCoreResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class UsgsAnomalyService {

    private static final String ALERT_TYPE = "ANOMALY_ALERT";
    private static final String RULE_CODE = "USGS_IFOREST_V1";
    /** Product path: turbidity on-demand IF (replaces legacy 5-D global pkl). */
    private static final String TURB_PARAM = "63680";

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final MonitorStationRepository monitorStationRepository;
    private final AlertEventRepository alertEventRepository;

    @Retry(name = "waterAiForecastRetry")
    public UsgsAnomalyResponse detectAndAlertFromIv(UsgsAnomalyFromIvRequest fromIv) {
        String site = fromIv.getSiteNo() != null ? fromIv.getSiteNo().trim() : "";
        String csv = fromIv.getIvCsvPath();
        if (csv != null && csv.isBlank()) {
            csv = null;
        }
        UsgsIvLatestCoreResponse snap = waterAiMaintenanceClient.fetchLatestCoreParams(
                UsgsIvLatestCoreRequest.builder().siteNo(site).ivCsvPath(csv).build()
        );
        SiteParamAnomalyIvRequest py = SiteParamAnomalyIvRequest.builder()
                .siteNo(site)
                .parameterCd(TURB_PARAM)
                .ivCsvPath(csv)
                .build();
        SiteParamAnomalyIvResponse sp = waterAiMaintenanceClient.anomalySiteParamFromIv(py);
        UsgsAnomalyResponse out = mapFromSiteParam(sp);
        out.setSampleDatetime(snap.getSampleDatetime());
        out.setImputedParams(snap.getImputedParams());
        out.setImputationNote(snap.getImputationNote());
        return finalizeAnomalyAlert(out, site);
    }

    @Retry(name = "waterAiForecastRetry")
    public UsgsAnomalyResponse detectAndAlert(UsgsAnomalyRequest request) {
        String siteNo = request.getSiteNo() != null ? request.getSiteNo().trim() : "";
        SiteParamAnomalyIvRequest py = SiteParamAnomalyIvRequest.builder()
                .siteNo(siteNo)
                .parameterCd(TURB_PARAM)
                .ivCsvPath(null)
                .build();
        SiteParamAnomalyIvResponse sp = waterAiMaintenanceClient.anomalySiteParamFromIv(py);
        UsgsAnomalyResponse out = mapFromSiteParam(sp);
        return finalizeAnomalyAlert(out, siteNo);
    }

    private static UsgsAnomalyResponse mapFromSiteParam(SiteParamAnomalyIvResponse sp) {
        UsgsAnomalyResponse out = new UsgsAnomalyResponse();
        out.setSiteNo(sp.getSiteNo());
        out.setModelVersion(sp.getModelVersion());
        out.setAnomalyScore(sp.getAnomalyScore());
        out.setThreshold(sp.getThreshold());
        if (sp.getAnomalyAvailable() == null || !sp.getAnomalyAvailable()) {
            out.setIsAnomaly(false);
            out.setAlertReason(sp.getReason() != null ? sp.getReason() : "unavailable");
            return out;
        }
        out.setIsAnomaly(Boolean.TRUE.equals(sp.getIsAnomaly()));
        return out;
    }

    private UsgsAnomalyResponse finalizeAnomalyAlert(UsgsAnomalyResponse out, String siteNo) {
        out.setAlertCreated(false);
        if (out.getIsAnomaly() == null || !out.getIsAnomaly()) {
            if (out.getAlertReason() == null) {
                out.setAlertReason("not_anomaly");
            }
            return out;
        }
        MonitorStation station = monitorStationRepository.findByExternalId(siteNo).orElse(null);
        if (station == null) {
            out.setAlertReason("station_not_registered");
            return out;
        }
        LocalDateTime dedupFrom = LocalDateTime.now().minusHours(6);
        boolean exists = alertEventRepository.existsByStationIdAndAlertTypeAndStatusInAndCreatedAtGreaterThanEqual(
                station.getId(), ALERT_TYPE, List.of("NEW", "ACK"), dedupFrom
        );
        if (exists) {
            out.setAlertReason("duplicate_suppressed");
            return out;
        }
        AlertEvent e = new AlertEvent();
        e.setStationId(station.getId());
        e.setAlertType(ALERT_TYPE);
        e.setSeverity("MEDIUM");
        e.setStatus("NEW");
        e.setPollutionLevel("ANOMALY");
        e.setTitle("USGS 参数异常预警");
        String impute = out.getImputationNote();
        e.setDetail(
                "site_no=" + siteNo
                        + ", score=" + out.getAnomalyScore()
                        + ", threshold=" + out.getThreshold()
                        + ", model=" + out.getModelVersion()
                        + (impute != null && !impute.isBlank() ? ", imputation=" + impute : "")
        );
        e.setRuleCode(RULE_CODE);
        e.setCreatedAt(LocalDateTime.now());
        alertEventRepository.save(e);
        out.setAlertCreated(true);
        out.setAlertReason("alert_created");
        return out;
    }
}
