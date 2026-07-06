package com.example.waterbusiness.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * USGS turbidity (63680) absolute threshold: two consecutive IV points; aligned to raw IV rows (no hourly resampling).
 */
@Data
@ConfigurationProperties(prefix = "water.turbidity-threshold")
public class TurbidityThresholdProperties {

    /**
     * Whether to register the scheduled scan (default true).
     */
    private boolean enabled = true;

    /**
     * Scan cron (default every 15 minutes on the clock).
     */
    private String cron = "0 */15 * * * ?";

    /**
     * Warning tier lower bound (NTU).
     */
    private double warnNtu = 50.0;

    /**
     * Critical tier lower bound (NTU).
     */
    private double criticalNtu = 100.0;

    /**
     * Dedup window in hours for same station and same tier.
     */
    private int dedupHours = 6;

    /**
     * Optional IV CSV path passed to Python; empty uses AI service default.
     */
    private String ivCsvPath;
}
