package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class UsgsAnomalyResponse {

    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    private String siteNo;

    @JsonProperty("model_version")
    @JsonAlias("modelVersion")
    private String modelVersion;

    @JsonProperty("anomaly_score")
    @JsonAlias("anomalyScore")
    private Double anomalyScore;

    private Double threshold;

    @JsonProperty("is_anomaly")
    @JsonAlias("isAnomaly")
    private Boolean isAnomaly;

    @JsonProperty("alert_created")
    private Boolean alertCreated;

    @JsonProperty("alert_reason")
    private String alertReason;

    /** Sample time (UTC ISO) when called via IV snapshot path */
    @JsonProperty("sample_datetime")
    @JsonAlias("sampleDatetime")
    private String sampleDatetime;

    /** Core params imputed with median (non-empty only on check-from-iv path) */
    @JsonProperty("imputed_params")
    private List<String> imputedParams;

    @JsonProperty("imputation_note")
    private String imputationNote;
}
