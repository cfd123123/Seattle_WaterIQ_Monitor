package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class TurbidityStateSnapshotRequest {

    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("features_csv_path")
    private String featuresCsvPath;

    @JsonProperty("thresholds_json_path")
    private String thresholdsJsonPath;

    @JsonProperty("reference_utc")
    private String referenceUtc;
}
