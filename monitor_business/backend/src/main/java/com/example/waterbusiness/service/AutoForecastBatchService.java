package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.AutoForecastBatchExecutionResult;
import com.example.waterbusiness.dto.AutoForecastBatchItemResult;
import com.example.waterbusiness.dto.ForecastResponse;
import com.example.waterbusiness.dto.ForecastSeriesPoint;
import com.example.waterbusiness.dto.ForecastSeriesRequest;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.MonitorStationRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Batch 00060/63680 trend forecasts for registered stations with non-empty externalId; updates {@link AutoForecastSettingsService#updateLastRun}.
 * Shared by the scheduler and the run-batch-now endpoint.
 */
@Service
@RequiredArgsConstructor
public class AutoForecastBatchService {

    private static final Logger log = LoggerFactory.getLogger(AutoForecastBatchService.class);

    private static final int FORECAST_PREVIEW_MAX_POINTS = 12;

    public static final List<String> PARAMETERS = List.of("00060", "63680");

    private final ForecastService forecastService;
    private final MonitorStationRepository monitorStationRepository;
    private final AutoForecastSettingsService autoForecastSettingsService;

    /**
     * @return persisted summary plus per-row batch details (scheduler may ignore)
     */
    public AutoForecastBatchExecutionResult executeBatch() {
        int ok = 0;
        int fail = 0;
        StringBuilder errs = new StringBuilder();
        List<AutoForecastBatchItemResult> items = new ArrayList<>();
        List<MonitorStation> all = monitorStationRepository.findAll();
        for (MonitorStation st : all) {
            String ext = st.getExternalId();
            if (ext == null || ext.isBlank()) {
                continue;
            }
            String site = ext.trim();
            String stationName = st.getStationName();
            for (String param : PARAMETERS) {
                try {
                    ForecastSeriesRequest req = new ForecastSeriesRequest();
                    req.setSiteNo(site);
                    req.setParameterCd(param);
                    req.setHorizonHours(24);
                    req.setHistoryDays(10);
                    ForecastResponse out = forecastService.forecastSeriesWithRetry(req);
                    items.add(toItemSuccess(site, stationName, param, out));
                    ok++;
                } catch (Exception e) {
                    fail++;
                    log.warn("forecast batch failed site_no={} parameter_cd={}: {}", site, param, e.getMessage());
                    items.add(toItemFailure(site, stationName, param, e.getMessage()));
                    if (errs.length() < 800) {
                        if (errs.length() > 0) {
                            errs.append("; ");
                        }
                        errs.append(site).append('/').append(param).append(':').append(e.getMessage());
                    }
                }
            }
        }
        String summary = "ok=" + ok + " fail=" + fail;
        if (!errs.isEmpty()) {
            summary += " | " + errs;
        }
        if (summary.length() > 2000) {
            summary = summary.substring(0, 1997) + "...";
        }
        autoForecastSettingsService.updateLastRun(LocalDateTime.now(), summary);
        log.info("forecast batch finished {}", summary);
        return new AutoForecastBatchExecutionResult(summary, items);
    }

    private static AutoForecastBatchItemResult toItemSuccess(
            String site,
            String stationName,
            String param,
            ForecastResponse out
    ) {
        return AutoForecastBatchItemResult.builder()
                .siteNo(site)
                .stationName(stationName)
                .parameterCd(param)
                .success(true)
                .forecastAvailable(out.getForecastAvailable())
                .forecastValue(out.getForecastValue())
                .reason(out.getReason())
                .forecastPollutionLevel(out.getForecastPollutionLevel())
                .forecastPointsPreview(takeTail(out.getForecastPoints(), FORECAST_PREVIEW_MAX_POINTS))
                .build();
    }

    private static AutoForecastBatchItemResult toItemFailure(
            String site,
            String stationName,
            String param,
            String message
    ) {
        return AutoForecastBatchItemResult.builder()
                .siteNo(site)
                .stationName(stationName)
                .parameterCd(param)
                .success(false)
                .errorMessage(truncateMessage(message, 400))
                .build();
    }

    private static List<ForecastSeriesPoint> takeTail(List<ForecastSeriesPoint> pts, int max) {
        if (pts == null || pts.isEmpty()) {
            return List.of();
        }
        int from = Math.max(0, pts.size() - max);
        return new ArrayList<>(pts.subList(from, pts.size()));
    }

    private static String truncateMessage(String s, int max) {
        if (s == null) {
            return null;
        }
        if (s.length() <= max) {
            return s;
        }
        return s.substring(0, max - 3) + "...";
    }
}
