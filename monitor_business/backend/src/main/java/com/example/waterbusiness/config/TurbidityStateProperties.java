package com.example.waterbusiness.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

/**
 * Turbidity alert-tier monitoring (Python {@code /turbidity/state/*}); see ai_service plan/turbidity_state_monitoring.md.
 */
@Data
@ConfigurationProperties(prefix = "water.turbidity-state")
public class TurbidityStateProperties {

    private boolean enabled = true;

    /** Cron for scheduled snapshot scan and optional alerts (default every 30 minutes). */
    private String cron = "0 */30 * * * ?";

    private int dedupHours = 6;

    /**
     * Hourly features CSV path passed to Python (relative to ai_service unless absolute).
     */
    private String featuresCsvPath = "data/features_12117500_63680_openmeteo_upstream_2022.csv";

    /**
     * Optional frozen thresholds JSON; empty uses tuning-segment estimation in Python.
     */
    private String thresholdsJsonPath = "";

    /**
     * USGS site numbers eligible for state monitoring (must match features CSV site).
     */
    private List<String> monitoredSiteNos = new ArrayList<>(List.of("12117500"));

    /** Fire STATE_ALERT when snapshot {@code alert_tier} is WATCH. */
    private boolean alertOnTierWatch = true;

    /** Fire STATE_ALERT when snapshot {@code alert_tier} is HIGH. */
    private boolean alertOnTierHigh = true;

    /** Fire STATE_ALERT when snapshot {@code alert_tier} is CRITICAL. */
    private boolean alertOnTierCritical = true;

    /** @deprecated use {@link #alertOnTierHigh}; kept for older property files */
    @Deprecated
    private boolean alertOnStateHigh = true;

    /** @deprecated use {@link #alertOnTierWatch}; kept for older property files */
    @Deprecated
    private boolean alertOnStateRising = true;

    private boolean alertOnRuleHorizon6 = true;

    private boolean alertOnRuleHorizon12 = true;
}
