package com.example.waterbusiness.service;

import com.example.waterbusiness.config.StatsProperties;
import com.example.waterbusiness.dto.StatsTrendPoint;
import com.example.waterbusiness.dto.StatsTrendResponse;
import com.example.waterbusiness.dto.StatsOverviewResponse;
import com.example.waterbusiness.dto.StatsDistributionResponse;
import com.example.waterbusiness.dto.StatsStationAlertTopItem;
import com.example.waterbusiness.dto.StatsStationAlertTopResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.UsgsSiteParamRun;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.ModelCallLogRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.example.waterbusiness.repository.UsgsSiteParamRunRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.lang.management.ManagementFactory;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Collections;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class StatsService {

    private static final String FORECAST_ALERT_TYPE = "FORECAST_THRESHOLD";
    private static final String FORECAST_RULE_CODE = "FORECAST_PARAM_THRESHOLD_V1";

    private final UsgsSiteParamRunRepository usgsSiteParamRunRepository;
    private final AlertEventRepository alertEventRepository;
    private final ModelCallLogRepository modelCallLogRepository;
    private final MonitorStationRepository monitorStationRepository;
    private final StatsProperties statsProperties;
    private static final Set<String> OPEN_ALERT_STATUSES = Set.of("NEW", "ACK");

    public StatsOverviewResponse overview() {
        LocalDate today = LocalDate.now();
        LocalDateTime todayStart = today.atStartOfDay();
        LocalDateTime tomorrowStart = today.plusDays(1).atStartOfDay();
        LocalDateTime last7DaysStart = today.minusDays(6).atStartOfDay();
        long uptimeSeconds = ManagementFactory.getRuntimeMXBean().getUptime() / 1000L;
        double uptimePercent30d = Math.min(100.0, (uptimeSeconds * 100.0) / (30.0 * 24.0 * 3600.0));
        uptimePercent30d = Math.round(uptimePercent30d * 10.0) / 10.0;

        return StatsOverviewResponse.builder()
                .totalCheckCount(usgsSiteParamRunRepository.count())
                .totalAlertCount(alertEventRepository.count())
                .totalAiFailureCount(modelCallLogRepository.countBySuccessIsFalse())
                .openAlertCount(alertEventRepository.countByStatusIn(new ArrayList<>(OPEN_ALERT_STATUSES)))
                .todayCheckCount(usgsSiteParamRunRepository.countByCreatedAtGreaterThanEqualAndCreatedAtLessThan(todayStart, tomorrowStart))
                .todayAlertCount(alertEventRepository.countByCreatedAtGreaterThanEqualAndCreatedAtLessThan(todayStart, tomorrowStart))
                .todayAiFailureCount(modelCallLogRepository.countByCreatedAtGreaterThanEqualAndCreatedAtLessThanAndSuccessIsFalse(todayStart, tomorrowStart))
                .last7DaysCheckCount(usgsSiteParamRunRepository.countByCreatedAtGreaterThanEqualAndCreatedAtLessThan(last7DaysStart, tomorrowStart))
                .last7DaysAlertCount(alertEventRepository.countByCreatedAtGreaterThanEqualAndCreatedAtLessThan(last7DaysStart, tomorrowStart))
                .last7DaysAiFailureCount(modelCallLogRepository.countByCreatedAtGreaterThanEqualAndCreatedAtLessThanAndSuccessIsFalse(last7DaysStart, tomorrowStart))
                .uptimeSeconds(uptimeSeconds)
                .uptimePercent30d(uptimePercent30d)
                .build();
    }

    public StatsDistributionResponse distribution(LocalDate from, LocalDate to) {
        if ((from == null) != (to == null)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "from 和 to 必须同时传，或都不传");
        }
        if (from != null && from.isAfter(to)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "from 不能晚于 to");
        }
        if (from != null) {
            validateRange(from, to);
        }

        List<Object[]> pollutionRows;
        List<Object[]> severityRows;
        if (from == null) {
            pollutionRows = alertEventRepository.countByPollutionLevelAll();
            severityRows = alertEventRepository.countBySeverityAll();
        } else {
            LocalDateTime fromTime = from.atStartOfDay();
            LocalDateTime toExclusive = to.plusDays(1).atStartOfDay();
            pollutionRows = alertEventRepository.countByPollutionLevelBetween(fromTime, toExclusive);
            severityRows = alertEventRepository.countBySeverityBetween(fromTime, toExclusive);
        }

        return StatsDistributionResponse.builder()
                .from(from)
                .to(to)
                .pollutionLevelDistribution(toDistributionMap(pollutionRows, StatsService::normalizePollutionLevel))
                .alertSeverityDistribution(toDistributionMap(severityRows, StatsService::normalizeSeverity))
                .build();
    }

    public StatsStationAlertTopResponse stationAlertTop(int days, int topN) {
        if (days < 1 || days > 30) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "days 仅支持 1-30");
        }
        if (topN < 1 || topN > 20) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "topN 仅支持 1-20");
        }
        LocalDate today = LocalDate.now();
        LocalDate fromDate = today.minusDays(days - 1L);
        LocalDateTime from = fromDate.atStartOfDay();
        LocalDateTime toExclusive = today.plusDays(1).atStartOfDay();
        List<Object[]> rows = alertEventRepository.topStationsByAlertCountBetween(
                from,
                toExclusive,
                PageRequest.of(0, topN)
        );
        List<StatsStationAlertTopItem> items = rows.stream()
                .map(row -> StatsStationAlertTopItem.builder()
                        .stationId(((Number) row[0]).longValue())
                        .stationCode((String) row[1])
                        .stationName((String) row[2])
                        .alertCount(((Number) row[3]).longValue())
                        .openAlertCount(((Number) row[4]).longValue())
                        .build())
                .toList();
        return StatsStationAlertTopResponse.builder()
                .days(days)
                .topN(topN)
                .items(items)
                .build();
    }

    @Cacheable(
            cacheNames = "statsTrend",
            key = "#from.toString() + ':' + #to.toString() + ':' + #granularity + ':' + (#stationId == null ? 'all' : #stationId)"
    )
    public StatsTrendResponse trend(LocalDate from, LocalDate to, String granularity, Long stationId) {
        if (!"day".equalsIgnoreCase(granularity)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "granularity 仅支持 day");
        }
        if (from.isAfter(to)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "from 不能晚于 to");
        }
        validateRange(from, to);

        if (stationId != null && !monitorStationRepository.existsById(stationId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "站点不存在: " + stationId);
        }

        LocalDateTime fromTime = from.atStartOfDay();
        LocalDateTime toExclusive = to.plusDays(1).atStartOfDay();

        List<AlertEvent> alerts;
        List<UsgsSiteParamRun> siteParamRuns;
        if (stationId == null) {
            alerts = alertEventRepository
                    .findByCreatedAtGreaterThanEqualAndCreatedAtLessThan(fromTime, toExclusive);
            siteParamRuns = usgsSiteParamRunRepository
                    .findByCreatedAtGreaterThanEqualAndCreatedAtLessThan(fromTime, toExclusive);
        } else {
            alerts = alertEventRepository
                    .findByStationIdAndCreatedAtGreaterThanEqualAndCreatedAtLessThan(
                            stationId, fromTime, toExclusive);
            siteParamRuns = usgsSiteParamRunRepository
                    .findByStationIdAndCreatedAtGreaterThanEqualAndCreatedAtLessThan(
                            stationId, fromTime, toExclusive);
        }

        Map<LocalDate, MutablePoint> bucket = initBucket(from, to);
        aggregateUsgsTrend(alerts, bucket);
        aggregateSiteParamRuns(siteParamRuns, bucket);

        List<StatsTrendPoint> series = new ArrayList<>();
        long totalFlowDet = 0;
        long totalFlowAnom = 0;
        long totalTurbDet = 0;
        long totalTurbAnom = 0;
        long totalAlerts = 0;
        for (Map.Entry<LocalDate, MutablePoint> entry : bucket.entrySet()) {
            MutablePoint p = entry.getValue();
            totalAlerts += p.allAlertsCount;
            totalFlowDet += p.flowDetectionCount;
            totalFlowAnom += p.flowAnomalyCount;
            totalTurbDet += p.turbidityDetectionCount;
            totalTurbAnom += p.turbidityAnomalyCount;
            series.add(StatsTrendPoint.builder()
                    .date(entry.getKey())
                    .checkCount(0)
                    .alertCount(p.allAlertsCount)
                    .aiFailureCount(0)
                    .pollutionLevelBreakdown(Collections.emptyMap())
                    .flowDetectionCount(p.flowDetectionCount)
                    .flowAnomalyCount(p.flowAnomalyCount)
                    .turbidityDetectionCount(p.turbidityDetectionCount)
                    .turbidityAnomalyCount(p.turbidityAnomalyCount)
                    .build());
        }

        return StatsTrendResponse.builder()
                .from(from)
                .to(to)
                .granularity("day")
                .stationId(stationId)
                .series(series)
                .totalCheckCount(0)
                .totalAlertCount(totalAlerts)
                .totalAiFailureCount(0)
                .totalFlowDetectionCount(totalFlowDet)
                .totalFlowAnomalyCount(totalFlowAnom)
                .totalTurbidityDetectionCount(totalTurbDet)
                .totalTurbidityAnomalyCount(totalTurbAnom)
                .build();
    }

    /** Counts successful per-site IV anomaly runs persisted; folded into the detection series (added to forecast alert counts). */
    private static void aggregateSiteParamRuns(List<UsgsSiteParamRun> runs, Map<LocalDate, MutablePoint> bucket) {
        for (UsgsSiteParamRun r : runs) {
            LocalDate date = r.getCreatedAt().toLocalDate();
            MutablePoint p = bucket.get(date);
            if (p == null) {
                continue;
            }
            if ("00060".equals(r.getParameterCd())) {
                p.flowDetectionCount++;
            } else if ("63680".equals(r.getParameterCd())) {
                p.turbidityDetectionCount++;
            }
        }
    }

    /**
     * Last-7-day trend: USGS-related alerts (forecast, IF anomaly, turbidity threshold) plus per-site param detection run counts.
     */
    private static void aggregateUsgsTrend(List<AlertEvent> alerts, Map<LocalDate, MutablePoint> bucket) {
        for (AlertEvent e : alerts) {
            LocalDate date = e.getCreatedAt().toLocalDate();
            MutablePoint point = bucket.get(date);
            if (point == null) {
                continue;
            }
            point.allAlertsCount++;
            categorizeUsgsAlert(e, point);
        }
    }

    private static void categorizeUsgsAlert(AlertEvent e, MutablePoint p) {
        String rc = e.getRuleCode();
        String title = e.getTitle() != null ? e.getTitle() : "";
        String at = e.getAlertType() != null ? e.getAlertType() : "";
        if (FORECAST_ALERT_TYPE.equals(at) && FORECAST_RULE_CODE.equals(rc)) {
            if (title.contains("00060")) {
                p.flowDetectionCount++;
            } else if (title.contains("63680")) {
                p.turbidityDetectionCount++;
            }
        }
        if ("SITE_PARAM_IF_00060".equals(rc)) {
            p.flowAnomalyCount++;
        }
        if ("SITE_PARAM_IF_63680".equals(rc)) {
            p.turbidityAnomalyCount++;
        }
        if (rc != null && rc.startsWith("USGS_TURBIDITY")) {
            p.turbidityAnomalyCount++;
        }
    }

    private static Map<LocalDate, MutablePoint> initBucket(LocalDate from, LocalDate to) {
        Map<LocalDate, MutablePoint> m = new LinkedHashMap<>();
        for (LocalDate d = from; !d.isAfter(to); d = d.plusDays(1)) {
            m.put(d, new MutablePoint());
        }
        return m;
    }

    private void validateRange(LocalDate from, LocalDate to) {
        long days = ChronoUnit.DAYS.between(from, to) + 1;
        int maxRangeDays = statsProperties.getMaxRangeDays();
        if (days > maxRangeDays) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "查询跨度不能超过 " + maxRangeDays + " 天"
            );
        }
    }

    private static String normalizePollutionLevel(String v) {
        if (v == null || v.isBlank()) {
            return "UNKNOWN";
        }
        String x = v.trim().toLowerCase(Locale.ROOT);
        return switch (x) {
            case "excellent" -> "Excellent";
            case "good" -> "Good";
            case "moderate" -> "Moderate";
            case "poor" -> "Poor";
            case "very poor" -> "Very Poor";
            default -> v.trim();
        };
    }

    private static String normalizeSeverity(String v) {
        if (v == null || v.isBlank()) {
            return "UNKNOWN";
        }
        String x = v.trim().toLowerCase(Locale.ROOT);
        return switch (x) {
            case "low" -> "LOW";
            case "medium" -> "MEDIUM";
            case "high" -> "HIGH";
            default -> v.trim().toUpperCase(Locale.ROOT);
        };
    }

    private interface KeyNormalizer {
        String normalize(String value);
    }

    private static Map<String, Long> toDistributionMap(List<Object[]> rows, KeyNormalizer keyNormalizer) {
        Map<String, Long> result = new LinkedHashMap<>();
        for (Object[] row : rows) {
            String key = keyNormalizer.normalize((String) row[0]);
            long value = ((Number) row[1]).longValue();
            result.put(key, value);
        }
        return result;
    }

    private static final class MutablePoint {
        long allAlertsCount;
        long flowDetectionCount;
        long flowAnomalyCount;
        long turbidityDetectionCount;
        long turbidityAnomalyCount;
    }
}
