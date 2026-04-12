package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.Map;

@Data
public class TurbidityThresholdBatchResponse {

    @JsonProperty("sites")
    private Map<String, TurbidityThresholdSiteSnapshotDto> sites;
}
