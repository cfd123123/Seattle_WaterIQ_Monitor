package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Stats overview response")
public class StatsOverviewResponse {

    @Schema(description = "Total checks", example = "1200")
    private long totalCheckCount;
    @Schema(description = "Total alerts", example = "180")
    private long totalAlertCount;
    @Schema(description = "Total AI failures", example = "12")
    private long totalAiFailureCount;
    @Schema(description = "Open alerts (NEW+ACK)", example = "25")
    private long openAlertCount;
    @Schema(description = "Today's checks", example = "20")
    private long todayCheckCount;
    @Schema(description = "Today's alerts", example = "4")
    private long todayAlertCount;
    @Schema(description = "Today's AI failures", example = "0")
    private long todayAiFailureCount;
    @Schema(description = "Last 7 days checks (incl. today)", example = "136")
    private long last7DaysCheckCount;
    @Schema(description = "Last 7 days alerts (incl. today)", example = "21")
    private long last7DaysAlertCount;
    @Schema(description = "Last 7 days AI failures (incl. today)", example = "2")
    private long last7DaysAiFailureCount;
    @Schema(description = "Current JVM uptime in seconds", example = "86400")
    private long uptimeSeconds;
    @Schema(description = "Rolling 30-day availability percentage (0-100)", example = "99.8")
    private double uptimePercent30d;
}
