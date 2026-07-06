package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class TurbidityRiskHorizonTierDto {

    @JsonProperty("horizon_h")
    private Integer horizonH;

    private String tier;
}
