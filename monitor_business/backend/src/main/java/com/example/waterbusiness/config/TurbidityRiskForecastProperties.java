package com.example.waterbusiness.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Phase B 12h turbidity risk forecast (Python {@code POST /turbidity/risk-forecast-12h}).
 */
@Data
@ConfigurationProperties(prefix = "water.turbidity-risk-forecast")
public class TurbidityRiskForecastProperties {

    private String featuresCsvPath = "data/features_12117500_63680_openmeteo_upstream_2022.csv";

    private String thresholdsJsonPath = "reports/turbidity_state/12117500_v2/state_thresholds.json";
}
