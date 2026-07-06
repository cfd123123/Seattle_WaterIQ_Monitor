package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/** Response from Python {@code POST /usgs/iv/latest-core-params}. */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class UsgsIvLatestCoreResponse {

    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("sample_datetime")
    private String sampleDatetime;

    @JsonProperty("v_00010")
    private Double v00010;

    @JsonProperty("v_00400")
    private Double v00400;

    @JsonProperty("v_00300")
    private Double v00300;

    @JsonProperty("v_00095")
    private Double v00095;

    @JsonProperty("v_63680")
    private Double v63680;

    /** parameter_cd values imputed with median (e.g. 00400) */
    @JsonProperty("imputed_params")
    private List<String> imputedParams;

    @JsonProperty("imputation_note")
    private String imputationNote;
}
