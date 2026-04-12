package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
@Schema(description = "USGS five-parameter anomaly detection request")
public class UsgsAnomalyRequest {

    @NotBlank
    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    private String siteNo;

    @NotNull
    @JsonProperty("v_00010")
    private Double v00010;

    @NotNull
    @JsonProperty("v_00400")
    private Double v00400;

    @NotNull
    @JsonProperty("v_00300")
    private Double v00300;

    @NotNull
    @JsonProperty("v_00095")
    private Double v00095;

    @NotNull
    @JsonProperty("v_63680")
    private Double v63680;
}
