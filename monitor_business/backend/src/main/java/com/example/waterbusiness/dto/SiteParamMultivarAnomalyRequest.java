package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
@Schema(description = "Multivariate turbidity IF on hourly features CSV (one snapshot)")
public class SiteParamMultivarAnomalyRequest {

    @NotBlank
    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("features_csv_path")
    private String featuresCsvPath;

    @JsonProperty("reference_utc")
    private String referenceUtc;
}
