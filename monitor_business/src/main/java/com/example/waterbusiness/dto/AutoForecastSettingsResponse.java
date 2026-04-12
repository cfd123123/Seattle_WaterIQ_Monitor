package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
@Schema(description = "Auto-forecast toggle and last scheduled run summary")
public class AutoForecastSettingsResponse {

    private boolean enabled;

    @JsonProperty("last_run_at")
    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss")
    private LocalDateTime lastRunAt;

    @JsonProperty("last_run_summary")
    private String lastRunSummary;

    @JsonProperty("schedule_cron")
    @Schema(description = "Effective Spring cron expression from configuration (for display)")
    private String scheduleCron;
}
