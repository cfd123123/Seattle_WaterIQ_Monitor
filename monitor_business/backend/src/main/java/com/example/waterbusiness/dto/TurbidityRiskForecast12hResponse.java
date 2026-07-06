package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class TurbidityRiskForecast12hResponse {

    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("model_version")
    private String modelVersion;

    @JsonProperty("phase_b_model")
    private String phaseBModel;

    @JsonProperty("reference_utc")
    private String referenceUtc;

    @JsonProperty("tier_at_t")
    private String tierAtT;

    @JsonProperty("turbidityNtu")
    @JsonAlias("63680")
    private Double turbidityNtu;

    @JsonProperty("alert_12h_forecast")
    private Integer alert12hForecast;

    @JsonProperty("max_tier_forecast")
    private String maxTierForecast;

    @JsonProperty("recommend_alert")
    private Boolean recommendAlert;

    @JsonProperty("rationale_template_key")
    private String rationaleTemplateKey;

    @JsonProperty("horizon_tiers")
    private List<TurbidityRiskHorizonTierDto> horizonTiers;

    /** LLM summary (MVP-1); absent when explain layer unavailable. */
    @JsonProperty("explanation_text")
    private String explanationText;

    @JsonProperty("explanation_model")
    private String explanationModel;

    @JsonProperty("explanation_provider")
    private String explanationProvider;

    @JsonProperty("explanation_generated_at")
    private String explanationGeneratedAt;

    /** Set by BFF when risk-explain returns 502/503 but forecast-12h succeeds. */
    @JsonProperty("explanation_error")
    private String explanationError;
}
