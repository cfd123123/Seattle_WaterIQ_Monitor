package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Stats trend response")
public class StatsTrendResponse {

    @Schema(description = "Range start", example = "2026-03-01")
    private LocalDate from;
    @Schema(description = "Range end", example = "2026-03-30")
    private LocalDate to;
    @Schema(description = "Granularity (currently day only)", example = "day")
    private String granularity;

    @JsonInclude(JsonInclude.Include.NON_NULL)
    @JsonProperty("station_id")
    @Schema(description = "When set, trend filtered to this station; null means all stations")
    private Long stationId;

    @Schema(description = "Daily series")
    private List<StatsTrendPoint> series;
    @Schema(description = "Total checks (legacy field, 0 in trend)", example = "0")
    private long totalCheckCount;
    @Schema(description = "Total alerts in range (including other types)", example = "30")
    private long totalAlertCount;
    @Schema(description = "Total AI failures (0 in trend)", example = "0")
    private long totalAiFailureCount;

    @Schema(description = "Total flow forecast-threshold alerts", example = "5")
    private long totalFlowDetectionCount;
    @Schema(description = "Total flow IF anomaly alerts", example = "5")
    private long totalFlowAnomalyCount;
    @Schema(description = "Total turbidity forecast-threshold alerts", example = "5")
    private long totalTurbidityDetectionCount;
    @Schema(description = "Total turbidity anomalies (IF + threshold family)", example = "5")
    private long totalTurbidityAnomalyCount;
}
