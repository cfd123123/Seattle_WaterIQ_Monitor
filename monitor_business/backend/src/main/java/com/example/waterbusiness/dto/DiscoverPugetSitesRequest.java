package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

import java.util.List;

/**
 * Mirrors {@code DiscoverPugetSitesRequest} in {@code ai_service/main.py} for NWIS Puget bbox discovery.
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
@Schema(description = "Optional body for POST /api/demo/puget-sites/discover")
public class DiscoverPugetSitesRequest {

    @Schema(description = "IV lookback days (1–90)", example = "30")
    private Integer days = 30;

    @JsonProperty("dry_run")
    @Schema(description = "If true, AI service does not write the JSON config file")
    private Boolean dryRun = false;

    @JsonProperty("merge_into_config")
    @Schema(description = "If false, only preview what would be merged (dry run)")
    private Boolean mergeIntoConfig = true;

    @JsonProperty("max_new")
    @Schema(description = "Max new sites appended per run")
    private Integer maxNew = 80;

    @Schema(description = "Optional [west, south, east, north] decimal degrees")
    private List<Double> bbox;
}
