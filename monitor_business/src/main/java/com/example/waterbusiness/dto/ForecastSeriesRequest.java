package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Data;

@Data
@Schema(description = "Forecast series request (history + future)")
public class ForecastSeriesRequest extends ForecastRequest {

    @Min(1)
    @Max(90)
    @JsonProperty("history_days")
    @JsonAlias("historyDays")
    @Schema(description = "History window in days for chart", example = "30")
    private Integer historyDays = 30;
}
