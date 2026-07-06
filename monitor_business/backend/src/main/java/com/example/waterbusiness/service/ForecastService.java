package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterForecastClient;
import com.example.waterbusiness.config.WaterAlertProperties;
import com.example.waterbusiness.domain.PollutionLevelThresholds;
import com.example.waterbusiness.dto.ForecastRequest;
import com.example.waterbusiness.dto.ForecastResponse;
import com.example.waterbusiness.dto.ForecastSeriesRequest;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class ForecastService {

    private static final Set<String> ALLOWED_FORECAST_PARAMETER_CD = Set.of("00060", "63680");

    private static final String FORECAST_ALERT_TYPE = "FORECAST_THRESHOLD";
    private static final String FORECAST_RULE_CODE = "FORECAST_PARAM_THRESHOLD_V1";

    private final WaterForecastClient waterForecastClient;
    private final MonitorStationRepository monitorStationRepository;
    private final AlertEventRepository alertEventRepository;
    private final WaterAlertProperties waterAlertProperties;

    @Retry(name = "waterAiForecastRetry")
    public ForecastResponse forecastWithRetry(ForecastRequest request) {
        requireAllowedForecastParameter(request.getParameterCd());
        if (request.getHorizonHours() == null) {
            request.setHorizonHours(24);
        }
        ForecastResponse out = waterForecastClient.forecast(request);
        enrichForecastAlert(request, out);
        return out;
    }

    @Retry(name = "waterAiForecastRetry")
    public ForecastResponse forecastSeriesWithRetry(ForecastSeriesRequest request) {
        requireAllowedForecastParameter(request.getParameterCd());
        if (request.getHorizonHours() == null) {
            request.setHorizonHours(24);
        }
        if (request.getHistoryDays() == null) {
            request.setHistoryDays(30);
        }
        ForecastResponse out = waterForecastClient.forecastSeries(request);
        enrichForecastAlert(request, out);
        return out;
    }

    private void enrichForecastAlert(ForecastRequest request, ForecastResponse out) {
        out.setForecastAlertCreated(false);
        if (out.getForecastAvailable() == null || !out.getForecastAvailable()) {
            out.setForecastAlertReason("forecast_unavailable");
            return;
        }
        String level = ForecastAlertPolicy.forecastLevel(out.getParameterCd(), out.getForecastValue());
        out.setForecastPollutionLevel(level);
        if (level == null) {
            out.setForecastAlertReason("unsupported_parameter_for_alert");
            return;
        }
        if (!ForecastAlertPolicy.shouldForecastAlert(level, waterAlertProperties.getThreshold())) {
            out.setForecastAlertReason("below_threshold");
            return;
        }
        String siteNo = request.getSiteNo() != null ? request.getSiteNo().trim() : "";
        MonitorStation station = monitorStationRepository.findByExternalId(siteNo).orElse(null);
        if (station == null) {
            out.setForecastAlertReason("station_not_registered");
            return;
        }
        // Dedupe: at most one NEW/ACK forecast alert per station/level within 6 hours.
        LocalDateTime dedupFrom = LocalDateTime.now().minusHours(6);
        boolean exists = alertEventRepository.existsByStationIdAndAlertTypeAndPollutionLevelAndStatusInAndCreatedAtGreaterThanEqual(
                station.getId(),
                FORECAST_ALERT_TYPE,
                level,
                List.of("NEW", "ACK"),
                dedupFrom
        );
        if (exists) {
            out.setForecastAlertReason("duplicate_suppressed");
            return;
        }
        int score = PollutionLevelThresholds.scoreOf(level);
        AlertEvent e = new AlertEvent();
        e.setStationId(station.getId());
        e.setAlertType(FORECAST_ALERT_TYPE);
        e.setSeverity(PollutionLevelThresholds.severityForScore(score));
        e.setStatus("NEW");
        e.setPollutionLevel(level);
        e.setTitle("预测预警: " + out.getParameterCd() + " -> " + level);
        e.setDetail(
                "site_no=" + siteNo
                        + ", horizon_hours=" + out.getHorizonHours()
                        + ", forecast_value=" + out.getForecastValue()
                        + ", model=" + out.getModelVersion()
        );
        e.setRuleCode(FORECAST_RULE_CODE);
        e.setCreatedAt(LocalDateTime.now());
        alertEventRepository.save(e);
        out.setForecastAlertCreated(true);
        out.setForecastAlertReason("alert_created");
    }

    private static void requireAllowedForecastParameter(String parameterCd) {
        String p = parameterCd != null ? parameterCd.trim() : "";
        if (!ALLOWED_FORECAST_PARAMETER_CD.contains(p)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "parameter_cd 仅支持流量 00060 或浊度 63680（当前不做水温等其它参数预测）"
            );
        }
    }
}
