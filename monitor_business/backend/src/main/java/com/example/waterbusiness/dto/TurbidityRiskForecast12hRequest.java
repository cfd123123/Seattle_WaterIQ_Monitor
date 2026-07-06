package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class TurbidityRiskForecast12hRequest {

    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("features_csv_path")
    private String featuresCsvPath;

    @JsonProperty("thresholds_json_path")
    private String thresholdsJsonPath;

    @JsonProperty("reference_utc")
    private String referenceUtc;
}
