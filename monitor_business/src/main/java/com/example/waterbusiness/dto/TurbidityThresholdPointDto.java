package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class TurbidityThresholdPointDto {

    private String datetime;

    private Double ntu;
}
