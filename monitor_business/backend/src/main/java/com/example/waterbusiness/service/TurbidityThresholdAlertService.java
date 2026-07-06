package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.config.TurbidityThresholdProperties;
import com.example.waterbusiness.dto.SitesWith63680Request;
import com.example.waterbusiness.dto.SitesWith63680Response;
import com.example.waterbusiness.dto.TurbidityThresholdBatchRequest;
import com.example.waterbusiness.dto.TurbidityThresholdBatchResponse;
import com.example.waterbusiness.dto.TurbidityThresholdPointDto;
import com.example.waterbusiness.dto.TurbidityThresholdScanResult;
import com.example.waterbusiness.dto.TurbidityThresholdSiteSnapshotDto;
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
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class TurbidityThresholdAlertService {

    private static final Logger log = LoggerFactory.getLogger(TurbidityThresholdAlertService.class);

    private static final String ALERT_TYPE = "THRESHOLD_ALERT";
    private static final String RULE_WARN = "USGS_TURBIDITY_THRESHOLD_V1_WARN";
    private static final String RULE_CRITICAL = "USGS_TURBIDITY_THRESHOLD_V1_CRITICAL";
    private static final String MODEL_LABEL = "USGS_TURBIDITY_THRESHOLD_V1";

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final MonitorStationRepository monitorStationRepository;
    private final AlertEventRepository alertEventRepository;
    private final TurbidityThresholdProperties properties;

    @Retry(name = "waterAiForecastRetry")
    public TurbidityThresholdScanResult scanAndAlert() {
        List<MonitorStation> registered = monitorStationRepository.findAll().stream()
                .filter(st -> st.getExternalId() != null && !st.getExternalId().isBlank())
                .toList();

        if (registered.isEmpty()) {
            return buildResult(0, 0, 0, 0, 0, 0, "no_registered_usgs_sites");
        }

        String ivCsv = blankToNull(properties.getIvCsvPath());
        SitesWith63680Response sitesWithResp = waterAiMaintenanceClient.sitesWith63680(
                SitesWith63680Request.builder().ivCsvPath(ivCsv).build()
        );
        Set<String> ivHas63680 = new HashSet<>();
        if (sitesWithResp != null && sitesWithResp.getSiteNos() != null) {
            for (String s : sitesWithResp.getSiteNos()) {
                if (s != null && !s.isBlank()) {
                    ivHas63680.add(s.trim());
                }
            }
        }

        List<MonitorStation> eligible = registered.stream()
                .filter(st -> ivHas63680.contains(st.getExternalId().trim()))
                .toList();
        int skippedRegisteredNo63680 = registered.size() - eligible.size();

        int considered = eligible.size();
        int alertsCreated = 0;
        int skipNoData = 0;
        int skipNoTrigger = 0;
        int skipDup = 0;

        if (eligible.isEmpty()) {
            String summary = String.format(
                    "considered=0 skipped_registered_no_63680_in_iv=%d created=0 no_data=0 no_trigger=0 dedup=0",
                    skippedRegisteredNo63680
            );
            log.info("turbidity threshold scan {}", summary);
            return buildResult(0, 0, 0, 0, 0, skippedRegisteredNo63680, summary);
        }

        List<String> siteNos = new ArrayList<>();
        for (MonitorStation st : eligible) {
            siteNos.add(st.getExternalId().trim());
        }

        TurbidityThresholdBatchRequest batchReq = TurbidityThresholdBatchRequest.builder()
                .siteNos(siteNos)
                .ivCsvPath(ivCsv)
                .build();
        TurbidityThresholdBatchResponse batch = waterAiMaintenanceClient.turbidityThresholdBatch(batchReq);
        Map<String, TurbidityThresholdSiteSnapshotDto> sites =
                batch != null && batch.getSites() != null ? batch.getSites() : Map.of();

        double warnN = properties.getWarnNtu();
        double critN = properties.getCriticalNtu();
        LocalDateTime dedupFrom = LocalDateTime.now().minusHours(properties.getDedupHours());

        for (MonitorStation station : eligible) {
            String site = station.getExternalId().trim();
            TurbidityThresholdSiteSnapshotDto snap = sites.get(site);
            if (snap == null || !snap.isAvailable()) {
                skipNoData++;
                continue;
            }
            List<TurbidityThresholdPointDto> pts = snap.getPoints();
            TurbidityThresholdRules.Tier tier = TurbidityThresholdRules.classify(pts, warnN, critN);
            if (tier == TurbidityThresholdRules.Tier.NONE) {
                skipNoTrigger++;
                continue;
            }
            String ruleCode = tier == TurbidityThresholdRules.Tier.CRITICAL ? RULE_CRITICAL : RULE_WARN;
            boolean exists = alertEventRepository.existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
                    station.getId(),
                    ALERT_TYPE,
                    ruleCode,
                    List.of("NEW", "ACK"),
                    dedupFrom
            );
            if (exists) {
                skipDup++;
                continue;
            }
            saveAlert(station, site, tier, pts, warnN, critN, ruleCode);
            alertsCreated++;
        }

        String summary = String.format(
                "considered=%d skipped_registered_no_63680_in_iv=%d created=%d no_data=%d no_trigger=%d dedup=%d",
                considered,
                skippedRegisteredNo63680,
                alertsCreated,
                skipNoData,
                skipNoTrigger,
                skipDup
        );
        log.info("turbidity threshold scan {}", summary);
        return buildResult(
                considered,
                alertsCreated,
                skipNoData,
                skipNoTrigger,
                skipDup,
                skippedRegisteredNo63680,
                summary
        );
    }

    private void saveAlert(
            MonitorStation station,
            String siteNo,
            TurbidityThresholdRules.Tier tier,
            List<TurbidityThresholdPointDto> pts,
            double warnN,
            double critN,
            String ruleCode
    ) {
        TurbidityThresholdPointDto p1 = pts.get(0);
        TurbidityThresholdPointDto p2 = pts.get(1);
        String severity = tier == TurbidityThresholdRules.Tier.CRITICAL ? "HIGH" : "MEDIUM";
        String pollution = tier == TurbidityThresholdRules.Tier.CRITICAL ? "Very Poor" : "Poor";
        String title = tier == TurbidityThresholdRules.Tier.CRITICAL
                ? "USGS 浊度阈值告警（严重）"
                : "USGS 浊度阈值告警（一般）";
        String detail = "site_no=" + siteNo
                + ", parameter_cd=63680"
                + ", tier=" + (tier == TurbidityThresholdRules.Tier.CRITICAL ? "critical" : "warn")
                + ", ntu_prev=" + p1.getNtu()
                + ", ntu_last=" + p2.getNtu()
                + ", threshold_warn=" + warnN
                + ", threshold_critical=" + critN
                + ", t_prev=" + (p1.getDatetime() != null ? p1.getDatetime() : "")
                + ", t_last=" + (p2.getDatetime() != null ? p2.getDatetime() : "")
                + ", model=" + MODEL_LABEL;
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

    private static TurbidityThresholdScanResult buildResult(
            int considered,
            int created,
            int noData,
            int noTrigger,
            int dedup,
            int skippedRegisteredNo63680InIv,
            String summary
    ) {
        return TurbidityThresholdScanResult.builder()
                .stationsConsidered(considered)
                .alertsCreated(created)
                .skippedNoData(noData)
                .skippedNoTrigger(noTrigger)
                .skippedDuplicate(dedup)
                .skippedRegisteredNo63680InIv(skippedRegisteredNo63680InIv)
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
