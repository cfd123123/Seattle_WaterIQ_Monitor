package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
@Schema(description = "Map marker snapshot for a station")
public class MapStationPointResponse {

    @Schema(description = "Station id", example = "1")
    private Long stationId;

    @Schema(description = "Station code", example = "puget_12117000")
    private String stationCode;

    @Schema(description = "Station name", example = "Puget sample (USGS 12117000)")
    private String stationName;

    @Schema(description = "Province or state", example = "Washington")
    private String province;

    @Schema(description = "City", example = "Seattle")
    private String city;

    @Schema(description = "Latitude", example = "47.6021")
    private Double latitude;

    @Schema(description = "Longitude", example = "-122.3350")
    private Double longitude;

    @Schema(description = "External site id (e.g. USGS site_no) for forecast hooks")
    private String externalId;

    @Schema(description = "Latest pollution level", example = "Poor")
    private String latestPollutionLevel;

    @Schema(description = "Latest sample time")
    private LocalDateTime latestSampleTime;

    @Schema(description = "Latest persist time")
    private LocalDateTime latestCreateTime;

    @Schema(description = "Open alert count", example = "2")
    private long openAlertCount;
}
