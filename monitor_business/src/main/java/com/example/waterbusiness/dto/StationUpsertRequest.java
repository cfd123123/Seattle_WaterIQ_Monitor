package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
@Schema(description = "Create or update station request")
public class StationUpsertRequest {

    @NotBlank(message = "stationCode 必填")
    @Schema(description = "Station code (unique)", example = "puget_12117000")
    private String stationCode;

    @Schema(description = "Station name", example = "Puget sample (USGS 12117000)")
    private String stationName;

    @Schema(description = "Province or state", example = "Washington")
    private String province;

    @Schema(description = "City", example = "Seattle")
    private String city;

    @NotNull(message = "latitude 必填")
    @Min(value = -90, message = "latitude 必须在 -90 到 90 之间")
    @Max(value = 90, message = "latitude 必须在 -90 到 90 之间")
    @Schema(description = "Latitude", example = "47.6021")
    private Double latitude;

    @NotNull(message = "longitude 必填")
    @Min(value = -180, message = "longitude 必须在 -180 到 180 之间")
    @Max(value = 180, message = "longitude 必须在 -180 到 180 之间")
    @Schema(description = "Longitude", example = "-122.3350")
    private Double longitude;

    @Schema(description = "Optional external ID, e.g. USGS 8-digit site_no (aligned with IV fetch)", example = "12117000")
    private String externalId;
}
