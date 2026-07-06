package com.example.waterbusiness.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Water-quality alert settings; threshold semantics see {@link com.example.waterbusiness.domain.PollutionLevelThresholds}.
 */
@Data
@ConfigurationProperties(prefix = "water.alert")
public class WaterAlertProperties {

    /**
     * After numeric mapping of pollution level, alert when value is greater than or equal (default 4 = Poor / Very Poor).
     */
    private int threshold = 4;
}
