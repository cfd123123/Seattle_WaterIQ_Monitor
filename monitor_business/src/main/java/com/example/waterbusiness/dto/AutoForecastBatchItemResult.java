package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.util.List;

/**
 * One station × parameter result inside an auto-forecast batch (for the run-batch-now UI).
 */
@Data
@Builder
@Schema(description = "Single row in auto-forecast batch result")
public class AutoForecastBatchItemResult {

    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("station_name")
    private String stationName;

    @JsonProperty("parameter_cd")
    private String parameterCd;

    @Schema(description = "Call completed without exception (forecast may still be unavailable)")
    private boolean success;

    @JsonProperty("forecast_available")
    private Boolean forecastAvailable;

    @JsonProperty("forecast_value")
    private Double forecastValue;

    private String reason;

    @JsonProperty("error_message")
    private String errorMessage;

    @JsonProperty("forecast_pollution_level")
    private String forecastPollutionLevel;

    @JsonProperty("forecast_points_preview")
    @Schema(description = "Tail of forecast points for mini sparkline")
    private List<ForecastSeriesPoint> forecastPointsPreview;
}
