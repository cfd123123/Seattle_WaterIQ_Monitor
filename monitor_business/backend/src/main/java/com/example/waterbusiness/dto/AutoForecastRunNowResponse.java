package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
@Schema(description = "Run batch now: updated settings plus per-station batch rows")
public class AutoForecastRunNowResponse {

    private AutoForecastSettingsResponse settings;

    @JsonProperty("batch_results")
    private List<AutoForecastBatchItemResult> batchResults;
}
