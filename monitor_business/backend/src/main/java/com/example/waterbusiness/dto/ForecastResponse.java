package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

import java.util.List;

/**
 * Maps Python /forecast response.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Short-horizon forecast result")
public class ForecastResponse {

    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    private String siteNo;

    @JsonProperty("parameter_cd")
    @JsonAlias("parameterCd")
    private String parameterCd;

    @JsonProperty("horizon_hours")
    @JsonAlias("horizonHours")
    private Integer horizonHours;

    @JsonProperty("forecast_available")
    @JsonAlias("forecastAvailable")
    @Schema(description = "Whether enough history exists to forecast")
    private Boolean forecastAvailable;

    @JsonProperty("forecast_value")
    @JsonAlias("forecastValue")
    private Double forecastValue;

    @JsonProperty("model_version")
    @JsonAlias("modelVersion")
    private String modelVersion;

    @JsonProperty("data_points_used")
    @JsonAlias("dataPointsUsed")
    private Integer dataPointsUsed;

    private String reason;

    @JsonProperty("series_last_timestamp")
    @JsonAlias("seriesLastTimestamp")
    private String seriesLastTimestamp;

    @JsonProperty("history_days")
    @JsonAlias("historyDays")
    private Integer historyDays;

    @JsonProperty("history_points")
    @JsonAlias("historyPoints")
    private List<ForecastSeriesPoint> historyPoints;

    @JsonProperty("forecast_points")
    @JsonAlias("forecastPoints")
    private List<ForecastSeriesPoint> forecastPoints;

    @JsonProperty("forecast_pollution_level")
    @JsonAlias("forecastPollutionLevel")
    private String forecastPollutionLevel;

    @JsonProperty("forecast_alert_created")
    @JsonAlias("forecastAlertCreated")
    private Boolean forecastAlertCreated;

    @JsonProperty("forecast_alert_reason")
    @JsonAlias("forecastAlertReason")
    private String forecastAlertReason;
}
