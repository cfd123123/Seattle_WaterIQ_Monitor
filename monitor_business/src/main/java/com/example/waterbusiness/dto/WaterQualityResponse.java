package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Water quality prediction result")
public class WaterQualityResponse {

    @JsonProperty("pollution_level")
    @JsonAlias("Pollution_Level")
    @Schema(description = "Pollution level", example = "Poor")
    private String pollutionLevel;

    /** Rule engine score 0–100; null in legacy model mode */
    @JsonProperty("score")
    @Schema(description = "Rule score 0–100 (Python in rule mode only)")
    private Double score;

    @JsonProperty("rule_version")
    @Schema(description = "Rule version label")
    private String ruleVersion;

    @JsonProperty("observed_count")
    @Schema(description = "Count of observed metrics (0–11)")
    private Integer observedCount;

    @JsonProperty("coverage_ratio")
    @Schema(description = "Coverage observed_count/11")
    private Double coverageRatio;

    @JsonProperty("imputed_fields")
    @Schema(description = "Field names treated as imputed / non-observed")
    private List<String> imputedFields;
}
