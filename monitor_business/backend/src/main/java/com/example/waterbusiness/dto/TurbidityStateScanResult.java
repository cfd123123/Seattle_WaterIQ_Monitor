package com.example.waterbusiness.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TurbidityStateScanResult {

    private int stationsConsidered;

    private int alertsCreated;

    private int skippedNoSnapshot;

    private int skippedNoTrigger;

    private int skippedDuplicate;

    private int skippedNotMonitored;

    private String summary;
}
