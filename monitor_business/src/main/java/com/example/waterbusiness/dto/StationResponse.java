package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
@Schema(description = "Station record")
public class StationResponse {

    @Schema(description = "Station id", example = "1")
    private Long id;

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

    @Schema(description = "External id (e.g. USGS site_no)")
    private String externalId;

    @Schema(description = "Status", example = "ACTIVE")
    private String status;

    @Schema(description = "Created at")
    private LocalDateTime createdAt;

    @Schema(description = "Updated at")
    private LocalDateTime updatedAt;
}
