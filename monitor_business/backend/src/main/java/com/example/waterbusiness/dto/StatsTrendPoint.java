package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Single-day trend point (USGS buckets from alert_event; legacy trend fields often 0)")
public class StatsTrendPoint {

    @Schema(description = "Date", example = "2026-03-29")
    private LocalDate date;
    @Schema(description = "Deprecated: legacy 11-param check count (always 0 in trend)", example = "0")
    private long checkCount;
    @Schema(description = "Total alerts that day (including types outside the four USGS buckets)", example = "2")
    private long alertCount;
    @Schema(description = "AI failures that day (always 0 in trend)", example = "0")
    private long aiFailureCount;
    @Schema(description = "Pollution level breakdown (empty in trend)")
    private Map<String, Long> pollutionLevelBreakdown;

    @Schema(description = "Flow: forecast threshold alerts persisted (FORECAST, parameter_cd=00060)", example = "1")
    private long flowDetectionCount;
    @Schema(description = "Flow: IF anomaly alerts (SITE_PARAM_IF_00060)", example = "0")
    private long flowAnomalyCount;
    @Schema(description = "Turbidity: forecast threshold alerts persisted (FORECAST, parameter_cd=63680)", example = "1")
    private long turbidityDetectionCount;
    @Schema(description = "Turbidity: anomalies (IF 63680 + USGS turbidity threshold family)", example = "2")
    private long turbidityAnomalyCount;
}
