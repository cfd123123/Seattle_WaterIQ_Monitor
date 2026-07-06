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
@Schema(description = "Stats distribution response")
public class StatsDistributionResponse {

    @Schema(description = "Range start (null = all time)", example = "2026-03-01")
    private LocalDate from;
    @Schema(description = "Range end (null = all time)", example = "2026-03-30")
    private LocalDate to;
    @Schema(description = "Pollution level distribution")
    private Map<String, Long> pollutionLevelDistribution;
    @Schema(description = "Alert severity distribution")
    private Map<String, Long> alertSeverityDistribution;
}
