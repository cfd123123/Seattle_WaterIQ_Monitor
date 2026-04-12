package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Single row in station alert TopN for last N days")
public class StatsStationAlertTopItem {

    @JsonProperty("station_id")
    private Long stationId;

    @JsonProperty("station_code")
    private String stationCode;

    @JsonProperty("station_name")
    private String stationName;

    @JsonProperty("alert_count")
    private long alertCount;

    @JsonProperty("open_alert_count")
    private long openAlertCount;
}
