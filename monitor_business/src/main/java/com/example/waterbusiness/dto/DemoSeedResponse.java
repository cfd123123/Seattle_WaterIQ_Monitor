package com.example.waterbusiness.dto;

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
@Schema(description = "Result of demo data seeding")
public class DemoSeedResponse {

    @Schema(description = "stationCode list for created demo stations")
    private List<String> stationCodes;

    @Schema(description = "Number of alert rows inserted")
    private int alertsInserted;

    @Schema(description = "Calendar days (yyyy-MM-dd) that had alerts, roughly half of the 7-day window")
    private List<String> seededDates;

    @Schema(description = "Human-readable message")
    private String message;
}
