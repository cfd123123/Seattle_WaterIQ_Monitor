package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Station alert TopN response for last N days")
public class StatsStationAlertTopResponse {

    private int days;

    @JsonProperty("top_n")
    private int topN;

    @JsonProperty("items")
    private List<StatsStationAlertTopItem> items;
}
