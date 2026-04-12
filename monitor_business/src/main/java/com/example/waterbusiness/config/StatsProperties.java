package com.example.waterbusiness.config;

import jakarta.validation.constraints.Min;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Data
@Validated
@ConfigurationProperties(prefix = "water.stats")
public class StatsProperties {

    /**
     * Max allowed range for trend/distribution (days, inclusive).
     */
    @Min(value = 1, message = "water.stats.max-range-days 必须大于等于 1")
    private int maxRangeDays = 365;
}
