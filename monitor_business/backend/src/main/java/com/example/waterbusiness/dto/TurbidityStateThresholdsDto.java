package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class TurbidityStateThresholdsDto {

    @JsonProperty("theta_low")
    private Double thetaLow;

    @JsonProperty("theta_high")
    private Double thetaHigh;
}
