package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Data;

/**
 * Proxies Python {@code POST /refresh/usgs-iv}.
 */
@Data
@Schema(description = "Manual USGS IV refresh: overwrite CSV for the last N days")
public class UsgsIvRefreshRequest {

    @Min(1)
    @Max(90)
    @Schema(description = "Lookback days (1–90); default 30 when omitted", example = "30")
    private Integer days;

    @Schema(
            description = "When true: after refresh, batch detect/persist latest row per USGS site (including threshold alerts);"
                    + " stationCode is attached only when monitor_station.external_id matches site_no"
    )
    private Boolean runChecksAfterRefresh;
}
