package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.DemoSeedResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Local/dev: seeds demo stations and alerts for testing 7-day station alert TopN; isolated from real USGS data (clean up via remark).
 */
@Service
@RequiredArgsConstructor
public class DemoSeedService {

    public static final String DEMO_REMARK = "DEMO_SEED_V1";

    private static final String FORECAST_TYPE = "FORECAST_THRESHOLD";
    private static final String FORECAST_RULE = "FORECAST_PARAM_THRESHOLD_V1";
    private static final String TURB_WARN_RULE = "USGS_TURBIDITY_THRESHOLD_V1_WARN";

    private final MonitorStationRepository monitorStationRepository;
    private final AlertEventRepository alertEventRepository;

    /**
     * Anchored on "today": 7-day stats window is [today-6, today] (same as {@link StatsService#stationAlertTop}).
     * Writes fake alerts on 4 calendar days (~half the window); three stations have decreasing counts for visible TopN ordering.
     */
    @Transactional
    public DemoSeedResponse seedFakeStationsAndAlerts() {
        alertEventRepository.deleteByRemark(DEMO_REMARK);

        LocalDate today = LocalDate.now();
        List<LocalDate> seededDays = new ArrayList<>();
        for (int d : new int[] { 0, 2, 4, 6 }) {
            seededDays.add(today.minusDays(6 - d));
        }

        List<MonitorStation> stations = upsertDemoStations(today);
        int inserted = 0;

        for (LocalDate day : seededDays) {
            LocalDateTime base = day.atTime(9, 0);
            MonitorStation s1 = stations.get(0);
            MonitorStation s2 = stations.get(1);
            MonitorStation s3 = stations.get(2);
            inserted += insertBundle(s1, base, 3);
            inserted += insertBundle(s2, base.plusMinutes(20), 2);
            inserted += insertBundle(s3, base.plusMinutes(40), 1);
        }

        List<String> codes = stations.stream().map(MonitorStation::getStationCode).toList();
        List<String> dateStrs = seededDays.stream().map(LocalDate::toString).toList();

        return DemoSeedResponse.builder()
                .stationCodes(codes)
                .alertsInserted(inserted)
                .seededDates(dateStrs)
                .message("已写入演示告警；刷新驾驶舱即可查看 TopN。再次调用会先删除同 remark 的旧演示告警后重写。")
                .build();
    }

    private List<MonitorStation> upsertDemoStations(LocalDate today) {
        List<DemoStationDef> defs = List.of(
                new DemoStationDef(
                        "FAKE_SEA_001",
                        "Demo Puget Alpha (fake)",
                        47.45,
                        -122.32,
                        "99000001"
                ),
                new DemoStationDef(
                        "FAKE_SEA_002",
                        "Demo Puget Beta (fake)",
                        47.50,
                        -122.28,
                        "99000002"
                ),
                new DemoStationDef(
                        "FAKE_SEA_003",
                        "Demo Puget Gamma (fake)",
                        47.55,
                        -122.35,
                        "99000003"
                )
        );
        List<MonitorStation> out = new ArrayList<>();
        LocalDateTime ts = today.atStartOfDay();
        for (DemoStationDef d : defs) {
            MonitorStation s = monitorStationRepository.findByStationCode(d.code).orElseGet(MonitorStation::new);
            s.setStationCode(d.code);
            s.setStationName(d.name);
            s.setProvince("WA");
            s.setCity("Seattle (demo)");
            s.setLatitude(d.lat);
            s.setLongitude(d.lng);
            s.setExternalId(d.externalId);
            s.setStatus("ACTIVE");
            if (s.getId() == null) {
                s.setCreatedAt(ts);
            }
            s.setUpdatedAt(ts);
            out.add(monitorStationRepository.save(s));
        }
        return out;
    }

    /** Per bundle: flow forecast alert + turbidity forecast alert + (optional) turbidity threshold; same rules as prod for stats/TopN. */
    private int insertBundle(MonitorStation station, LocalDateTime t, int variant) {
        int n = 0;
        n += saveAlert(
                station.getId(),
                t,
                FORECAST_TYPE,
                FORECAST_RULE,
                "MEDIUM",
                "NEW",
                "Poor",
                "[DEMO] 预测预警: 00060 -> Poor",
                "site_no=" + station.getExternalId() + ",demo_seed,parameter_cd=00060"
        );
        if (variant >= 2) {
            n += saveAlert(
                    station.getId(),
                    t.plusMinutes(5),
                    FORECAST_TYPE,
                    FORECAST_RULE,
                    "HIGH",
                    "NEW",
                    "Very Poor",
                    "[DEMO] 预测预警: 63680 -> Very Poor",
                    "site_no=" + station.getExternalId() + ",demo_seed,parameter_cd=63680"
            );
        }
        if (variant >= 3) {
            n += saveAlert(
                    station.getId(),
                    t.plusMinutes(10),
                    "THRESHOLD_ALERT",
                    TURB_WARN_RULE,
                    "MEDIUM",
                    "NEW",
                    "Poor",
                    "[DEMO] USGS 浊度阈值告警（一般）",
                    "site_no=" + station.getExternalId() + ",parameter_cd=63680,demo_seed"
            );
        }
        return n;
    }

    private int saveAlert(
            Long stationId,
            LocalDateTime createdAt,
            String alertType,
            String ruleCode,
            String severity,
            String status,
            String pollutionLevel,
            String title,
            String detail
    ) {
        AlertEvent e = new AlertEvent();
        e.setStationId(stationId);
        e.setWaterQualityRecordId(null);
        e.setAlertType(alertType);
        e.setRuleCode(ruleCode);
        e.setSeverity(severity);
        e.setStatus(status);
        e.setPollutionLevel(pollutionLevel);
        e.setTitle(title.length() > 200 ? title.substring(0, 200) : title);
        e.setDetail(detail.length() > 1000 ? detail.substring(0, 1000) : detail);
        e.setRemark(DEMO_REMARK);
        e.setCreatedAt(createdAt);
        alertEventRepository.save(e);
        return 1;
    }

    private record DemoStationDef(String code, String name, double lat, double lng, String externalId) {}
}
