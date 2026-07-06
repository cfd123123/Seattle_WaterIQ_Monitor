package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.config.TurbidityStateProperties;
import com.example.waterbusiness.dto.TurbidityStateCheckResponse;
import com.example.waterbusiness.dto.TurbidityStateHorizonWarningDto;
import com.example.waterbusiness.dto.TurbidityStateScanResult;
import com.example.waterbusiness.dto.TurbidityStateSnapshotRequest;
import com.example.waterbusiness.dto.TurbidityStateSnapshotResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class TurbidityStateAlertService {

    private static final Logger log = LoggerFactory.getLogger(TurbidityStateAlertService.class);

    static final String ALERT_TYPE = "STATE_ALERT";
    static final String MODEL_LABEL = "TURBIDITY_STATE_V2";
    static final String RULE_TIER_CRITICAL = "TURBIDITY_STATE_V2_CRITICAL";
    static final String RULE_TIER_HIGH = "TURBIDITY_STATE_V2_HIGH";
    static final String RULE_TIER_WATCH = "TURBIDITY_STATE_V2_WATCH";
    static final String RULE_WARN_H6 = "TURBIDITY_STATE_V1_RULE_H6";
    static final String RULE_WARN_H12 = "TURBIDITY_STATE_V1_RULE_H12";

    /** @deprecated legacy v1 four-state rule */
    static final String RULE_STATE_HIGH = "TURBIDITY_STATE_V1_HIGH";

    /** @deprecated legacy v1 four-state rule */
    static final String RULE_STATE_RISING = "TURBIDITY_STATE_V1_RISING";

    /** Missing-y tiers from Python v2.1; never emit STATE_ALERT. */
    static final Set<String> GAP_TIERS = Set.of("SENSOR_GAP", "DATA_STALE", "UNKNOWN");

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final MonitorStationRepository monitorStationRepository;
    private final AlertEventRepository alertEventRepository;
    private final TurbidityStateProperties properties;

    @Retry(name = "waterAiForecastRetry")
    public TurbidityStateSnapshotResponse fetchSnapshot(String siteNo, String referenceUtc) {
        String site = normalizeSite(siteNo);
        TurbidityStateSnapshotRequest req = buildPythonRequest(site, referenceUtc);
        return waterAiMaintenanceClient.turbidityStateSnapshot(req);
    }

    @Retry(name = "waterAiForecastRetry")
    public TurbidityStateCheckResponse checkAndAlert(String siteNo, String referenceUtc) {
        TurbidityStateSnapshotResponse snap = fetchSnapshot(siteNo, referenceUtc);
        TurbidityStateCheckResponse out = TurbidityStateCheckResponse.builder()
                .snapshot(snap)
                .alertCreated(false)
                .alertReason("no_trigger")
                .build();
        if (snap == null || !hasActionableSnapshot(snap)) {
            out.setAlertReason("snapshot_unavailable");
            return out;
        }
        String site = snap.getSiteNo() != null ? snap.getSiteNo().trim() : normalizeSite(siteNo);
        if (!isMonitoredSite(site)) {
            out.setAlertReason("site_not_monitored");
            return out;
        }
        MonitorStation station = monitorStationRepository.findByExternalId(site).orElse(null);
        if (station == null) {
            out.setAlertReason("station_not_registered");
            return out;
        }
        int created = createAlertsForSnapshot(station, snap);
        if (created > 0) {
            out.setAlertCreated(true);
            out.setAlertReason("alert_created");
        }
        return out;
    }

    @Retry(name = "waterAiForecastRetry")
    public TurbidityStateScanResult scanAndAlert() {
        Set<String> monitored = monitoredSiteSet();
        List<MonitorStation> registered = monitorStationRepository.findAll().stream()
                .filter(st -> st.getExternalId() != null && !st.getExternalId().isBlank())
                .toList();

        if (registered.isEmpty()) {
            return buildResult(0, 0, 0, 0, 0, 0, "no_registered_usgs_sites");
        }

        int considered = 0;
        int alertsCreated = 0;
        int skipNoSnapshot = 0;
        int skipNoTrigger = 0;
        int skipDup = 0;
        int skipNotMonitored = 0;

        for (MonitorStation station : registered) {
            String site = station.getExternalId().trim();
            if (!monitored.contains(site)) {
                skipNotMonitored++;
                continue;
            }
            considered++;
            TurbidityStateSnapshotResponse snap;
            try {
                snap = fetchSnapshot(site, null);
            } catch (Exception ex) {
                log.warn("turbidity state snapshot failed site={}: {}", site, ex.getMessage());
                skipNoSnapshot++;
                continue;
            }
            if (snap == null || !hasActionableSnapshot(snap)) {
                skipNoSnapshot++;
                continue;
            }
            int triggers = countTriggers(snap);
            int created = createAlertsForSnapshot(station, snap);
            alertsCreated += created;
            if (triggers == 0) {
                skipNoTrigger++;
            } else if (created == 0) {
                skipDup += triggers;
            } else if (created < triggers) {
                skipDup += triggers - created;
            }
        }

        String summary = String.format(
                "considered=%d created=%d no_snapshot=%d no_trigger=%d dedup=%d not_monitored=%d",
                considered,
                alertsCreated,
                skipNoSnapshot,
                skipNoTrigger,
                skipDup,
                skipNotMonitored
        );
        log.info("turbidity state scan {}", summary);
        return buildResult(considered, alertsCreated, skipNoSnapshot, skipNoTrigger, skipDup, skipNotMonitored, summary);
    }

    private int createAlertsForSnapshot(MonitorStation station, TurbidityStateSnapshotResponse snap) {
        int created = 0;
        LocalDateTime dedupFrom = LocalDateTime.now().minusHours(properties.getDedupHours());

        String tier = resolvedAlertTier(snap);
        if (tier != null) {
            if (isGapTier(tier)) {
                return 0;
            }
            if ("CRITICAL".equals(tier) && properties.isAlertOnTierCritical()) {
                return maybeSaveAlert(station, snap, RULE_TIER_CRITICAL, "HIGH", "Very Poor",
                        "USGS 浊度告警（严重）", dedupFrom) ? 1 : 0;
            }
            if ("HIGH".equals(tier) && properties.isAlertOnTierHigh()) {
                return maybeSaveAlert(station, snap, RULE_TIER_HIGH, "HIGH", "Very Poor",
                        "USGS 浊度告警（高）", dedupFrom) ? 1 : 0;
            }
            if ("WATCH".equals(tier) && properties.isAlertOnTierWatch()) {
                return maybeSaveAlert(station, snap, RULE_TIER_WATCH, "MEDIUM", "Poor",
                        "USGS 浊度告警（关注）", dedupFrom) ? 1 : 0;
            }
            return 0;
        }

        String state = snap.getState();
        if (properties.isAlertOnStateHigh() && "High".equals(state)) {
            created += maybeSaveAlert(station, snap, RULE_STATE_HIGH, "HIGH", "Very Poor",
                    "USGS 浊度状态告警（高浊度）", dedupFrom) ? 1 : 0;
            return created;
        }
        if (properties.isAlertOnStateRising() && "Rising".equals(state)) {
            created += maybeSaveAlert(station, snap, RULE_STATE_RISING, "MEDIUM", "Poor",
                    "USGS 浊度状态告警（上升）", dedupFrom) ? 1 : 0;
            return created;
        }

        Map<String, TurbidityStateHorizonWarningDto> horizons = snap.getWarningHorizons();
        if (horizons == null) {
            return 0;
        }
        if (properties.isAlertOnRuleHorizon6()) {
            TurbidityStateHorizonWarningDto h6 = horizons.get("6");
            if (h6 != null && Boolean.TRUE.equals(h6.getRuleFires())) {
                created += maybeSaveAlert(station, snap, RULE_WARN_H6, "MEDIUM", "Poor",
                        "USGS 浊度前瞻预警（6 小时内高浊度风险）", dedupFrom) ? 1 : 0;
            }
        }
        if (properties.isAlertOnRuleHorizon12()) {
            TurbidityStateHorizonWarningDto h12 = horizons.get("12");
            if (h12 != null && Boolean.TRUE.equals(h12.getRuleFires())) {
                created += maybeSaveAlert(station, snap, RULE_WARN_H12, "MEDIUM", "Poor",
                        "USGS 浊度前瞻预警（12 小时内高浊度风险）", dedupFrom) ? 1 : 0;
            }
        }
        return created;
    }

    private int countTriggers(TurbidityStateSnapshotResponse snap) {
        String tier = resolvedAlertTier(snap);
        if (tier != null) {
            if (isGapTier(tier)) {
                return 0;
            }
            if ("CRITICAL".equals(tier) && properties.isAlertOnTierCritical()) {
                return 1;
            }
            if ("HIGH".equals(tier) && properties.isAlertOnTierHigh()) {
                return 1;
            }
            if ("WATCH".equals(tier) && properties.isAlertOnTierWatch()) {
                return 1;
            }
            return 0;
        }

        String state = snap.getState();
        if ("High".equals(state) && properties.isAlertOnStateHigh()) {
            return 1;
        }
        if ("Rising".equals(state) && properties.isAlertOnStateRising()) {
            return 1;
        }

        int n = 0;
        Map<String, TurbidityStateHorizonWarningDto> h = snap.getWarningHorizons();
        if (h != null) {
            if (properties.isAlertOnRuleHorizon6()) {
                TurbidityStateHorizonWarningDto w6 = h.get("6");
                if (w6 != null && Boolean.TRUE.equals(w6.getRuleFires())) {
                    n++;
                }
            }
            if (properties.isAlertOnRuleHorizon12()) {
                TurbidityStateHorizonWarningDto w12 = h.get("12");
                if (w12 != null && Boolean.TRUE.equals(w12.getRuleFires())) {
                    n++;
                }
            }
        }
        return n;
    }

    static boolean isGapTier(String tier) {
        return tier != null && GAP_TIERS.contains(tier);
    }

    private static String resolvedAlertTier(TurbidityStateSnapshotResponse snap) {
        if (snap.getAlertTier() != null && !snap.getAlertTier().isBlank()) {
            return snap.getAlertTier().trim().toUpperCase();
        }
        return null;
    }

    private static boolean hasActionableSnapshot(TurbidityStateSnapshotResponse snap) {
        if (resolvedAlertTier(snap) != null) {
            return true;
        }
        return snap.getState() != null;
    }

    private boolean maybeSaveAlert(
            MonitorStation station,
            TurbidityStateSnapshotResponse snap,
            String ruleCode,
            String severity,
            String pollution,
            String title,
            LocalDateTime dedupFrom
    ) {
        boolean exists = alertEventRepository.existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
                station.getId(),
                ALERT_TYPE,
                ruleCode,
                List.of("NEW", "ACK"),
                dedupFrom
        );
        if (exists) {
            return false;
        }
        saveAlert(station, snap, ruleCode, severity, pollution, title);
        return true;
    }

    private void saveAlert(
            MonitorStation station,
            TurbidityStateSnapshotResponse snap,
            String ruleCode,
            String severity,
            String pollution,
            String title
    ) {
        String siteNo = snap.getSiteNo() != null ? snap.getSiteNo() : station.getExternalId();
        String tier = resolvedAlertTier(snap);
        String detail = "site_no=" + siteNo
                + ", parameter_cd=63680"
                + ", alert_tier=" + (tier != null ? tier : "")
                + ", state=" + snap.getState()
                + ", ntu=" + snap.getTurbidityNtu()
                + ", diff_1h=" + snap.getDiff1h()
                + ", reference_utc=" + (snap.getReferenceUtc() != null ? snap.getReferenceUtc() : "")
                + ", is_anomaly=" + snap.getIsAnomaly()
                + ", model=" + (snap.getModelVersion() != null ? snap.getModelVersion() : MODEL_LABEL);
        if (snap.getThresholds() != null) {
            detail += ", theta_low=" + snap.getThresholds().getThetaLow()
                    + ", theta_high=" + snap.getThresholds().getThetaHigh();
        }
        Map<String, TurbidityStateHorizonWarningDto> horizons = snap.getWarningHorizons();
        if (horizons != null) {
            TurbidityStateHorizonWarningDto w6 = horizons.get("6");
            TurbidityStateHorizonWarningDto w12 = horizons.get("12");
            if (w6 != null) {
                detail += ", rule_h6=" + w6.getRuleFires();
            }
            if (w12 != null) {
                detail += ", rule_h12=" + w12.getRuleFires();
            }
        }
        AlertEvent e = new AlertEvent();
        e.setStationId(station.getId());
        e.setAlertType(ALERT_TYPE);
        e.setSeverity(severity);
        e.setStatus("NEW");
        e.setPollutionLevel(pollution);
        e.setTitle(title);
        e.setDetail(detail);
        e.setRuleCode(ruleCode);
        e.setCreatedAt(LocalDateTime.now());
        alertEventRepository.save(e);
    }

    private TurbidityStateSnapshotRequest buildPythonRequest(String siteNo, String referenceUtc) {
        return TurbidityStateSnapshotRequest.builder()
                .siteNo(siteNo)
                .featuresCsvPath(blankToNull(properties.getFeaturesCsvPath()))
                .thresholdsJsonPath(blankToNull(properties.getThresholdsJsonPath()))
                .referenceUtc(blankToNull(referenceUtc))
                .build();
    }

    private Set<String> monitoredSiteSet() {
        Set<String> out = new HashSet<>();
        if (properties.getMonitoredSiteNos() != null) {
            for (String s : properties.getMonitoredSiteNos()) {
                if (s != null && !s.isBlank()) {
                    out.add(s.trim());
                }
            }
        }
        return out;
    }

    private boolean isMonitoredSite(String siteNo) {
        return monitoredSiteSet().contains(siteNo);
    }

    private static String normalizeSite(String siteNo) {
        if (siteNo == null || siteNo.isBlank()) {
            return "12117500";
        }
        return siteNo.trim();
    }

    private static TurbidityStateScanResult buildResult(
            int considered,
            int created,
            int noSnapshot,
            int noTrigger,
            int dedup,
            int notMonitored,
            String summary
    ) {
        return TurbidityStateScanResult.builder()
                .stationsConsidered(considered)
                .alertsCreated(created)
                .skippedNoSnapshot(noSnapshot)
                .skippedNoTrigger(noTrigger)
                .skippedDuplicate(dedup)
                .skippedNotMonitored(notMonitored)
                .summary(summary)
                .build();
    }

    private static String blankToNull(String s) {
        if (!StringUtils.hasText(s)) {
            return null;
        }
        return s.trim();
    }
}
