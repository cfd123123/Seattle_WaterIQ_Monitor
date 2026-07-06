package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.Map;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class TurbidityStateSnapshotResponse {

    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("model_version")
    private String modelVersion;

    @JsonProperty("reference_utc")
    private String referenceUtc;

    /** Python snapshot uses NWIS key {@code 63680}; API exposes {@code turbidityNtu} to the UI. */
    @JsonProperty("turbidityNtu")
    @JsonAlias("63680")
    private Double turbidityNtu;

    private String state;

    @JsonProperty("alert_tier")
    private String alertTier;

    @JsonProperty("diff_1h")
    private Double diff1h;

    @JsonProperty("is_anomaly")
    private Boolean isAnomaly;

    @JsonProperty("warning_horizons")
    private Map<String, TurbidityStateHorizonWarningDto> warningHorizons;

    private TurbidityStateThresholdsDto thresholds;
}
