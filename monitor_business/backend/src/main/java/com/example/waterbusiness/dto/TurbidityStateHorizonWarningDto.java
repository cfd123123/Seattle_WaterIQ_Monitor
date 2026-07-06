package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class TurbidityStateHorizonWarningDto {

    @JsonProperty("rule_fires")
    private Boolean ruleFires;

    @JsonProperty("future_high_in_window")
    private Boolean futureHighInWindow;
}
