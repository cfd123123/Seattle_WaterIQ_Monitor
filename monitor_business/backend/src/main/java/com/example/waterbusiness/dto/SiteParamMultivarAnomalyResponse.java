package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class SiteParamMultivarAnomalyResponse {

    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    private String siteNo;

    @JsonProperty("anomaly_available")
    @JsonAlias("anomalyAvailable")
    private Boolean anomalyAvailable;

    private String reason;

    @JsonProperty("samples_used")
    @JsonAlias("samplesUsed")
    private Integer samplesUsed;

    @JsonProperty("sample_timestamp")
    @JsonAlias("sampleTimestamp")
    private String sampleTimestamp;

    @JsonProperty("model_version")
    @JsonAlias("modelVersion")
    private String modelVersion;

    @JsonProperty("is_anomaly")
    @JsonAlias("isAnomaly")
    private Boolean isAnomaly;
}
